import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..db import get_pool
from ..redis_client import get_redis, SUBMISSION_QUEUE
from ..auth import get_current_team
from .events import event_status

router = APIRouter(prefix="/submissions", tags=["submissions"])

# Anti-starvation limits, enforced in Redis so they hold across API replicas
# and so a crashed/restarted request can't leak a permanent slot.
SUBMISSION_COOLDOWN_SECONDS = int(os.environ.get("SUBMISSION_COOLDOWN_SECONDS", "60"))
SUBMISSIONS_PER_HOUR = int(os.environ.get("SUBMISSIONS_PER_HOUR", "20"))

class SubmitIn(BaseModel):
    challenge_slug: str
    files: dict[str, str]   # { "Freshness.ts": "<file content>", ... }

async def check_rate_limits(r, event_id: str, team_id: str) -> None:
    """
    Raise 429 if the team is mid-cooldown or has hit its hourly cap.
    The hourly count is read (not incremented) before the cooldown is armed,
    so an over-cap rejection doesn't also cost the team a cooldown slot.
    """
    # Fixed-window hourly cap, keyed by hour-of-epoch so it rolls over without cleanup.
    hour = int(datetime.now(timezone.utc).timestamp() // 3600)
    count_key = f"hackfest:sub_count:{event_id}:{team_id}:{hour}"
    if int(await r.get(count_key) or 0) >= SUBMISSIONS_PER_HOUR:
        raise HTTPException(429, f"hourly submission limit reached ({SUBMISSIONS_PER_HOUR}/h)")

    cooldown_key = f"hackfest:cooldown:{event_id}:{team_id}"
    # SET NX EX arms the cooldown: the lock self-expires, so a request that
    # dies after this check but before queueing can't wedge the team out.
    ok = await r.set(cooldown_key, "1", nx=True, ex=SUBMISSION_COOLDOWN_SECONDS)
    if not ok:
        ttl = await r.ttl(cooldown_key)
        raise HTTPException(
            429,
            f"submission cooldown active: try again in {max(ttl, 1)}s "
            f"({SUBMISSION_COOLDOWN_SECONDS}s between submissions)",
        )

    # Cooldown slot won — count the submission against the hourly cap.
    await r.incr(count_key)
    if await r.ttl(count_key) < 0:  # key just created this hour
        await r.expire(count_key, 3600)

@router.post("")
async def submit(body: SubmitIn, team=Depends(get_current_team)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow("SELECT start_at, end_at FROM events WHERE id=$1", team["event_id"])
        status = event_status(event["start_at"], event["end_at"])
        if status != "running":
            # This is the real enforcement point: the server clock decides,
            # never the browser. A submission after end_at is rejected even
            # if the team's local clock still shows time remaining.
            raise HTTPException(403, f"event is not running (status: {status})")

        challenge = await conn.fetchrow(
            "SELECT id, editable_files FROM challenges WHERE event_id=$1 AND slug=$2",
            team["event_id"], body.challenge_slug,
        )
        if not challenge:
            raise HTTPException(404, "no such challenge")

        allowed = set(challenge["editable_files"])
        submitted = set(body.files.keys())
        if not submitted.issubset(allowed):
            raise HTTPException(400, f"unexpected files: {sorted(submitted - allowed)}")

        # Rate-limit *after* validation so malformed submissions (wrong event
        # status, bad filenames) don't burn a team's cooldown or hourly slot.
        await check_rate_limits(get_redis(), str(team["event_id"]), str(team["team_id"]))

        row = await conn.fetchrow(
            """
            INSERT INTO submissions (challenge_id, team_id, files, status)
            VALUES ($1, $2, $3, 'queued')
            RETURNING id
            """,
            challenge["id"], team["team_id"], json.dumps(body.files),
        )
        submission_id = str(row["id"])

    # Hand off to a judge worker. The worker does all the risky work
    # (spinning up a container with these files) outside the request path.
    r = get_redis()
    await r.rpush(SUBMISSION_QUEUE, submission_id)
    return {"submission_id": submission_id, "status": "queued"}

@router.get("/{submission_id}")
async def get_submission(submission_id: str, team=Depends(get_current_team)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, checks, submitted_at, graded_at FROM submissions WHERE id=$1 AND team_id=$2",
            submission_id, team["team_id"],
        )
        if not row:
            raise HTTPException(404, "no such submission")
        return {
            "id": str(row["id"]),
            "status": row["status"],
            "checks": row["checks"],
            "submitted_at": row["submitted_at"].isoformat(),
            "graded_at": row["graded_at"].isoformat() if row["graded_at"] else None,
        }
