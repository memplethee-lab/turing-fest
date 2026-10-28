"""
Admin routes: create/edit events and challenges, monitor teams and
submissions, regrade a stuck submission, export final scores.

Auth model: a single shared admin password (ADMIN_PASSWORD env var) issues
an admin-scoped JWT via /admin/login. That's enough for a one-day event run
by a small organizing team; swap for real per-admin accounts if you reuse
this platform repeatedly or with a larger ops team.
"""
import csv
import io
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import get_pool
from ..redis_client import get_redis, leaderboard_key, SUBMISSION_QUEUE
from ..auth import create_admin_token, get_current_admin

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class LoginIn(BaseModel):
    password: str


@router.post("/login")
async def admin_login(body: LoginIn):
    if not ADMIN_PASSWORD:
        raise HTTPException(500, "ADMIN_PASSWORD is not configured on the server")
    # Plain compare is fine here: this is one shared operator secret set via
    # environment config, not a per-user password stored at rest — nothing
    # to hash against. Rotate ADMIN_PASSWORD between events.
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(401, "wrong admin password")
    return {"token": create_admin_token()}


# ---------- events ----------

class EventIn(BaseModel):
    name: str
    start_at: datetime
    end_at: datetime
    freeze_at: datetime | None = None


class EventPatch(BaseModel):
    name: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    freeze_at: datetime | None = None


@router.post("/events")
async def create_event(body: EventIn, admin=Depends(get_current_admin)):
    if body.end_at <= body.start_at:
        raise HTTPException(400, "end_at must be after start_at")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO events (name, start_at, end_at, freeze_at) VALUES ($1,$2,$3,$4) RETURNING id",
            body.name, body.start_at, body.end_at, body.freeze_at,
        )
        return {"id": str(row["id"])}


@router.get("/events")
async def list_events(admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, start_at, end_at, freeze_at FROM events ORDER BY start_at DESC"
        )
        return [
            {
                "id": str(r["id"]), "name": r["name"],
                "start_at": r["start_at"].isoformat(), "end_at": r["end_at"].isoformat(),
                "freeze_at": r["freeze_at"].isoformat() if r["freeze_at"] else None,
            }
            for r in rows
        ]


@router.patch("/events/{event_id}")
async def update_event(event_id: str, body: EventPatch, admin=Depends(get_current_admin)):
    # Build the SET clause from whichever fields were actually supplied, so
    # e.g. extending end_at mid-event doesn't require resending everything.
    fields, values = [], []
    for i, (key, val) in enumerate(body.model_dump(exclude_unset=True).items(), start=1):
        fields.append(f"{key} = ${i}")
        values.append(val)
    if not fields:
        raise HTTPException(400, "no fields to update")
    values.append(event_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE events SET {', '.join(fields)} WHERE id = ${len(values)}", *values
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "no such event")
    return {"ok": True}


# ---------- challenges ----------

class ChallengeIn(BaseModel):
    event_id: str
    slug: str
    title: str
    points: int = 100
    time_bonus_points: int = 0
    editable_files: list[str]
    briefing_md: str


@router.post("/challenges")
async def create_challenge(body: ChallengeIn, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM challenges WHERE event_id=$1 AND slug=$2", body.event_id, body.slug
        )
        if existing:
            raise HTTPException(409, "a challenge with this slug already exists for this event")
        row = await conn.fetchrow(
            """
            INSERT INTO challenges (event_id, slug, title, points, time_bonus_points, editable_files, briefing_md)
            VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id
            """,
            body.event_id, body.slug, body.title, body.points,
            body.time_bonus_points, body.editable_files, body.briefing_md,
        )
        return {"id": str(row["id"])}


@router.get("/events/{event_id}/challenges")
async def list_challenges_admin(event_id: str, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, slug, title, points, time_bonus_points, editable_files FROM challenges WHERE event_id=$1 ORDER BY title",
            event_id,
        )
        return [dict(r) for r in rows]


@router.delete("/challenges/{challenge_id}")
async def delete_challenge(challenge_id: str, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM challenges WHERE id=$1", challenge_id)
        if result == "DELETE 0":
            raise HTTPException(404, "no such challenge")
    return {"ok": True}


# ---------- teams & scores ----------

@router.get("/events/{event_id}/teams")
async def list_teams(event_id: str, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.name, t.created_at,
                   COALESCE(SUM(s.points_awarded), 0) AS total_points,
                   COUNT(s.id) AS solves
            FROM teams t
            LEFT JOIN solves s ON s.team_id = t.id
            WHERE t.event_id = $1
            GROUP BY t.id
            ORDER BY total_points DESC, t.created_at ASC
            """,
            event_id,
        )
        return [
            {
                "id": str(r["id"]), "name": r["name"],
                "created_at": r["created_at"].isoformat(),
                "total_points": r["total_points"], "solves": r["solves"],
            }
            for r in rows
        ]


# ---------- submissions monitor ----------

@router.get("/events/{event_id}/submissions")
async def list_submissions(event_id: str, status: str | None = None, limit: int = 100,
                            admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT s.id, s.status, s.submitted_at, s.graded_at,
                   t.name AS team_name, c.title AS challenge_title
            FROM submissions s
            JOIN teams t ON t.id = s.team_id
            JOIN challenges c ON c.id = s.challenge_id
            WHERE c.event_id = $1
        """
        args = [event_id]
        if status:
            query += " AND s.status = $2"
            args.append(status)
        query += " ORDER BY s.submitted_at DESC LIMIT " + str(min(limit, 500))
        rows = await conn.fetch(query, *args)
        return [
            {
                "id": str(r["id"]), "status": r["status"],
                "team_name": r["team_name"], "challenge_title": r["challenge_title"],
                "submitted_at": r["submitted_at"].isoformat(),
                "graded_at": r["graded_at"].isoformat() if r["graded_at"] else None,
            }
            for r in rows
        ]


@router.post("/submissions/{submission_id}/regrade")
async def regrade_submission(submission_id: str, admin=Depends(get_current_admin)):
    """
    Re-queues a submission that errored out (e.g. a worker crashed mid-grade,
    or Docker hiccuped). Does not re-run anything automatically — regrading
    is a deliberate admin action, since re-queuing a `passed` submission
    could theoretically award a duplicate solve if your worker logic ever
    changes; the current worker's UNIQUE(challenge_id, team_id) constraint
    on `solves` already prevents a double-award either way.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM submissions WHERE id=$1", submission_id)
        if not row:
            raise HTTPException(404, "no such submission")
        await conn.execute("UPDATE submissions SET status='queued' WHERE id=$1", submission_id)
    r = get_redis()
    await r.rpush(SUBMISSION_QUEUE, submission_id)
    return {"ok": True}


# ---------- export ----------

@router.get("/events/{event_id}/export.csv")
async def export_scores_csv(event_id: str, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.name, COALESCE(SUM(s.points_awarded), 0) AS total_points, COUNT(s.id) AS solves
            FROM teams t
            LEFT JOIN solves s ON s.team_id = t.id
            WHERE t.event_id = $1
            GROUP BY t.id
            ORDER BY total_points DESC
            """,
            event_id,
        )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["rank", "team", "points", "solves"])
    for i, r in enumerate(rows, start=1):
        writer.writerow([i, r["name"], r["total_points"], r["solves"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=results-{event_id}.csv"},
    )


# ---------- freeze-aware leaderboard snapshot ----------

@router.post("/events/{event_id}/freeze-now")
async def freeze_now(event_id: str, admin=Depends(get_current_admin)):
    """
    Manually snapshot the current leaderboard into a frozen key, and set
    freeze_at to now if it wasn't already set. The public leaderboard route
    checks for this frozen key and serves it instead of the live one once
    past freeze_at — see routes/leaderboard.py.
    """
    pool = await get_pool()
    r = get_redis()
    live_key = leaderboard_key(event_id)
    frozen_key = f"{live_key}:frozen"
    entries = await r.zrevrange(live_key, 0, -1, withscores=True)
    if entries:
        await r.delete(frozen_key)
        await r.zadd(frozen_key, {team_id: score for team_id, score in entries})
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE events SET freeze_at = COALESCE(freeze_at, now()) WHERE id=$1", event_id
        )
    return {"ok": True, "frozen_entries": len(entries)}
