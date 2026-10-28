"""
Judge worker: pops submission IDs off the Redis queue, grades each one in a
throwaway, locked-down Docker container, writes the result back to Postgres,
and updates the leaderboard + solves table on a pass.

Run several of these (docker-compose `deploy.replicas`) — they're
independent and only coordinate through the Redis queue (BLPOP is atomic,
so two workers never grab the same submission).
"""
import asyncio
import json
import os
import tarfile
import io
import time
from datetime import datetime, timezone

import asyncpg
import docker
import redis.asyncio as redis
import yaml

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
SUBMISSION_QUEUE = "hackfest:submissions"
CHALLENGES_DIR = "/challenges"

GRADE_TIMEOUT_SECONDS = 30   # a hidden test suite should never legitimately need longer
MEMORY_LIMIT = "512m"
CPU_QUOTA = 100_000          # ~1 CPU (docker cpu_period default 100000)

docker_client = docker.from_env()


def load_challenge_meta(slug: str) -> dict:
    with open(f"{CHALLENGES_DIR}/{slug}/meta.yaml") as f:
        return yaml.safe_load(f)


def build_submission_tar(files: dict[str, str]) -> bytes:
    """Package the team's submitted files into a tar stream for docker cp."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def grade_submission(slug: str, files: dict[str, str]) -> dict:
    """
    Runs the challenge's image with the team's files copied over the
    vulnerable ones, then runs its verify script inside the SAME locked-down
    container — no network, bounded memory/CPU, a hard wall-clock timeout,
    and removed unconditionally afterward.

    This is the one place in the whole system that executes untrusted code.
    Treat any change here as security-sensitive.
    """
    meta = load_challenge_meta(slug)
    image = meta["image"]           # e.g. "hackfest/webhook-replay:latest"
    editable_dir = meta["editable_dir"]   # path inside the image, e.g. "/app/editable"
    verify_cmd = meta["verify_cmd"]       # e.g. ["bash", "verify.sh"]

    container = docker_client.containers.run(
        image,
        command="sleep infinity",   # keep it alive so we can cp files in, then exec verify
        detach=True,
        network_disabled=True,      # no network access at all — this is the big one
        mem_limit=MEMORY_LIMIT,
        memswap_limit=MEMORY_LIMIT, # disable swap beyond the mem limit
        cpu_quota=CPU_QUOTA,
        pids_limit=128,             # fork-bomb guard
        read_only=False,            # challenge needs to compile/run; editable_dir itself could be tmpfs-only if you want it tighter
        security_opt=["no-new-privileges"],
        cap_drop=["ALL"],
        remove=False,               # we remove manually in `finally` so we can always reach logs on failure
    )

    try:
        # Copy the team's submitted files into the challenge's editable dir.
        tar_bytes = build_submission_tar(files)
        container.put_archive(editable_dir, tar_bytes)

        exec_result = container.exec_run(verify_cmd, workdir=editable_dir, demux=True)
        stdout, stderr = exec_result.output
        output_text = (stdout or b"").decode("utf-8", "replace") + (stderr or b"").decode("utf-8", "replace")

        try:
            parsed = json.loads(output_text.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            # verify.sh should print one JSON line; if it didn't, treat as a
            # grading error rather than guessing pass/fail from free text.
            return {"status": "error", "checks": None, "raw_output": output_text[-4000:]}

        passed = bool(parsed.get("passed"))
        return {
            "status": "passed" if passed else "failed",
            "checks": parsed.get("checks", []),
        }

    except Exception as e:
        return {"status": "error", "checks": None, "raw_output": str(e)}

    finally:
        try:
            container.kill()
        except docker.errors.APIError:
            pass
        try:
            container.remove(force=True)
        except docker.errors.APIError:
            pass


async def award_solve(conn: asyncpg.Connection, r: redis.Redis, submission_id: str,
                       challenge_id: str, team_id: str, event_id: str, base_points: int,
                       time_bonus_points: int, event_start, event_end):
    already = await conn.fetchrow(
        "SELECT id FROM solves WHERE challenge_id=$1 AND team_id=$2", challenge_id, team_id
    )
    if already:
        return  # first solve already scored; resubmitting a passing fix doesn't add more points

    now = datetime.now(timezone.utc)
    total_seconds = max((event_end - event_start).total_seconds(), 1)
    elapsed = (now - event_start).total_seconds()
    fraction_remaining = max(0.0, 1.0 - elapsed / total_seconds)
    bonus = int(time_bonus_points * fraction_remaining)
    points = base_points + bonus

    await conn.execute(
        """
        INSERT INTO solves (challenge_id, team_id, submission_id, points_awarded)
        VALUES ($1, $2, $3, $4)
        """,
        challenge_id, team_id, submission_id, points,
    )

    totals = await conn.fetchrow(
        "SELECT COALESCE(SUM(points_awarded), 0) AS total FROM solves WHERE team_id=$1", team_id
    )
    seconds_since_start = int(elapsed)
    score = totals["total"] * 1_000_000_000 - seconds_since_start
    await r.zadd(f"hackfest:leaderboard:{event_id}", {team_id: score})


async def main():
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    r = redis.from_url(REDIS_URL, decode_responses=True)

    print("judge worker started, waiting for submissions...")
    while True:
        _, submission_id = await r.blpop(SUBMISSION_QUEUE)

        async with pool.acquire() as conn:
            sub = await conn.fetchrow(
                """
                SELECT s.id, s.files, s.challenge_id, s.team_id,
                       c.slug, c.points, c.time_bonus_points, c.event_id
                FROM submissions s JOIN challenges c ON c.id = s.challenge_id
                WHERE s.id = $1
                """,
                submission_id,
            )
            if not sub:
                continue

            await conn.execute("UPDATE submissions SET status='running' WHERE id=$1", submission_id)

        files = json.loads(sub["files"]) if isinstance(sub["files"], str) else sub["files"]

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, grade_submission, sub["slug"], files),
                timeout=GRADE_TIMEOUT_SECONDS + 10,  # outer safety net beyond the container's own limits
            )
        except asyncio.TimeoutError:
            result = {"status": "error", "checks": None, "raw_output": "grading timed out"}

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE submissions SET status=$1, checks=$2, graded_at=now() WHERE id=$3",
                result["status"], json.dumps(result.get("checks")), submission_id,
            )

            if result["status"] == "passed":
                event = await conn.fetchrow(
                    "SELECT start_at, end_at FROM events WHERE id=$1", sub["event_id"]
                )
                await award_solve(
                    conn, r, str(sub["id"]), str(sub["challenge_id"]), str(sub["team_id"]),
                    str(sub["event_id"]), sub["points"], sub["time_bonus_points"],
                    event["start_at"], event["end_at"],
                )

        print(f"graded {submission_id}: {result['status']}")


if __name__ == "__main__":
    asyncio.run(main())
