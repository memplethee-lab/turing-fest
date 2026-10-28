from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from ..db import get_pool

router = APIRouter(prefix="/events", tags=["events"])

def event_status(start_at: datetime, end_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    if now < start_at:
        return "not_started"
    if now > end_at:
        return "ended"
    return "running"

@router.get("/{event_id}")
async def get_event(event_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, start_at, end_at, freeze_at FROM events WHERE id=$1", event_id
        )
        if not row:
            raise HTTPException(404, "no such event")
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "start_at": row["start_at"].isoformat(),
            "end_at": row["end_at"].isoformat(),
            "freeze_at": row["freeze_at"].isoformat() if row["freeze_at"] else None,
            "status": event_status(row["start_at"], row["end_at"]),
            "server_time": datetime.now(timezone.utc).isoformat(),  # clients should trust this, not their own clock
        }
