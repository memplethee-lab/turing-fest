import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from ..db import get_pool
from ..redis_client import get_redis, leaderboard_key

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


async def _effective_key(event_id: str) -> str:
    """
    Once an event's freeze_at has passed, serve the frozen snapshot key
    instead of the live one — set by POST /admin/events/{id}/freeze-now.
    Falls back to the live key if freeze_at isn't set, or hasn't passed yet.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT freeze_at FROM events WHERE id=$1", event_id)
    live_key = leaderboard_key(event_id)
    if row and row["freeze_at"] and datetime.now(timezone.utc) >= row["freeze_at"]:
        frozen_key = f"{live_key}:frozen"
        r = get_redis()
        if await r.exists(frozen_key):
            return frozen_key
    return live_key


@router.get("/{event_id}")
async def get_leaderboard(event_id: str, limit: int = 100):
    r = get_redis()
    key = await _effective_key(event_id)
    # ZREVRANGE: highest encoded score first == most points, earliest solve wins ties
    entries = await r.zrevrange(key, 0, limit - 1, withscores=True)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM teams WHERE event_id=$1", event_id)
        names = {str(row["id"]): row["name"] for row in rows}

    return {
        "entries": [
            {"team_id": team_id, "team_name": names.get(team_id, "?"), "score": score}
            for team_id, score in entries
        ],
        "frozen": key.endswith(":frozen"),
    }

@router.get("/{event_id}/stream")
async def stream_leaderboard(event_id: str):
    """
    Server-sent events: pushes the leaderboard every 2s. Good enough for 50
    teams; swap for a Redis pub/sub trigger instead of polling if you want
    truly instant updates, but polling is far simpler to get right.

    Stops updating once the event is frozen — keeps re-sending the same
    frozen snapshot rather than the live (possibly still-changing) set, so
    a team can't infer late changes by watching the stream twitch.
    """
    async def event_generator():
        r = get_redis()
        while True:
            key = await _effective_key(event_id)
            entries = await r.zrevrange(key, 0, 99, withscores=True)
            yield {"event": "leaderboard", "data": json.dumps({"entries": entries, "frozen": key.endswith(":frozen")})}
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())
