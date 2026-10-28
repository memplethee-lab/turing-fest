from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..db import get_pool
from ..redis_client import get_redis
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
            # Server-side truth for the workspace's countdown display. Gating
            # still happens by server clock on submission — the browser uses
            # this only for the visibly remaining time.
            "start_at": event["start_at"].isoformat(),
            "end_at": event["end_at"].isoformat(),
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

@router.get("/{slug}/start")
async def get_start_files(slug: str, team=Depends(get_current_team)):
    """
    Starting content of every editable file — what the workspace editor opens
    with. Reads the challenge_files seed table (admin-managed), NOT the image
    or anything build-time, so only ever exposes team-facing content.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow("SELECT start_at, end_at FROM events WHERE id=$1", team["event_id"])
        if event_status(event["start_at"], event["end_at"]) == "not_started":
            raise HTTPException(403, "event has not started yet")
        row = await conn.fetchrow(
            "SELECT id FROM challenges WHERE event_id=$1 AND slug=$2", team["event_id"], slug
        )
        if not row:
            raise HTTPException(404, "no such challenge")
        files = await conn.fetch(
            "SELECT filename, content FROM challenge_files WHERE challenge_id=$1", row["id"]
        )
        return {
            "challenge_id": str(row["id"]),
            "files": {r["filename"]: r["content"] for r in files},
        }


_DRAFT_TTL_SECONDS = 7 * 86400
_DRAFT_MAX_BYTES = 128 * 1024


class DraftIn(BaseModel):
    content: str


def _draft_key(event_id: str, team_id: str, slug: str, filename: str) -> str:
    return f"hackfest:draft:{event_id}:{team_id}:{slug}:{filename}"


@router.put("/{slug}/draft/{filename}")
async def put_draft(slug: str, filename: str, body: DraftIn, team=Depends(get_current_team)):
    """Server-side autosave of in-editor work. Not a submission: no rate
    limit, no grading, expires after a week. Lives only under the calling
    team's key — one team can never read another team's draft."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        allowed = await conn.fetchval(
            "SELECT editable_files FROM challenges WHERE event_id=$1 AND slug=$2",
            team["event_id"], slug,
        )
    if not allowed:
        raise HTTPException(404, "no such challenge")
    if filename not in allowed:
        raise HTTPException(400, f"unexpected file: {filename}")
    if len(body.content.encode("utf-8")) > _DRAFT_MAX_BYTES:
        raise HTTPException(413, "draft too large")
    r = get_redis()
    await r.set(
        _draft_key(str(team["event_id"]), str(team["team_id"]), slug, filename),
        body.content,
        ex=_DRAFT_TTL_SECONDS,
    )
    return {"ok": True}


@router.get("/{slug}/draft/{filename}")
async def get_draft(slug: str, filename: str, team=Depends(get_current_team)):
    r = get_redis()
    content = await r.get(
        _draft_key(str(team["event_id"]), str(team["team_id"]), slug, filename)
    )
    return {"content": content if isinstance(content, str) else (content or b"").decode("utf-8", "strict")}


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
