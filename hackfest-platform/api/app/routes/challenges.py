from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from ..db import get_pool
from ..auth import get_current_team
from .events import event_status

router = APIRouter(prefix="/challenges", tags=["challenges"])

@router.get("")
async def list_challenges(team=Depends(get_current_team)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT start_at, end_at FROM events WHERE id=$1", team["event_id"]
        )
        status = event_status(event["start_at"], event["end_at"])
        if status == "not_started":
            # Challenges stay hidden before the event opens, even to an
            # authenticated team — the briefing text is the thing we don't
            # want leaking early.
            return {"status": status, "challenges": []}

        rows = await conn.fetch(
            """
            SELECT c.id, c.slug, c.title, c.points, c.editable_files,
                   (s.id IS NOT NULL) AS solved
            FROM challenges c
            LEFT JOIN solves s ON s.challenge_id = c.id AND s.team_id = $2
            WHERE c.event_id = $1
            ORDER BY c.title
            """,
            team["event_id"], team["team_id"],
        )
        return {
            "status": status,
            "challenges": [
                {
                    "id": str(r["id"]),
                    "slug": r["slug"],
                    "title": r["title"],
                    "points": r["points"],
                    "editable_files": r["editable_files"],
                    "solved": r["solved"],
                }
                for r in rows
            ],
        }

@router.get("/{slug}")
async def get_challenge(slug: str, team=Depends(get_current_team)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow("SELECT start_at, end_at FROM events WHERE id=$1", team["event_id"])
        status = event_status(event["start_at"], event["end_at"])
        if status == "not_started":
            raise HTTPException(403, "event has not started yet")

        row = await conn.fetchrow(
            "SELECT id, title, points, editable_files, briefing_md FROM challenges WHERE event_id=$1 AND slug=$2",
            team["event_id"], slug,
        )
        if not row:
            raise HTTPException(404, "no such challenge")
        return dict(row)
