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

@router.get("/current")
async def current_event():
    """The event a participant should be signing up for: the one running now,
    else the next one to start, else the most recent one. The workspace uses
    this instead of asking people to paste an event id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, start_at, end_at, freeze_at, registration_mode FROM events"
        )
    if not rows:
        raise HTTPException(404, "no events yet")
    now = datetime.now(timezone.utc)

    def sort_key(row):
        status = event_status(row["start_at"], row["end_at"])
        if status == "running":
            return (0, 0.0)
        if status == "not_started":
            return (1, (row["start_at"] - now).total_seconds())
        return (2, (now - row["end_at"]).total_seconds())

    row = min(rows, key=sort_key)
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "start_at": row["start_at"].isoformat(),
        "end_at": row["end_at"].isoformat(),
        "status": event_status(row["start_at"], row["end_at"]),
        "registration_mode": row["registration_mode"],
        "server_time": now.isoformat(),
    }


# Public list of events, newest first. The workspace signs people into the
# running event (/current); this listing is for pages that need to offer a
# choice when an organizer runs more than one event.
@router.get("")
async def list_events():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, start_at, end_at, freeze_at FROM events ORDER BY start_at DESC"
        )
        return [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "start_at": r["start_at"].isoformat(),
                "end_at": r["end_at"].isoformat(),
                "freeze_at": r["freeze_at"].isoformat() if r["freeze_at"] else None,
                "status": event_status(r["start_at"], r["end_at"]),
            }
            for r in rows
        ]


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
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
