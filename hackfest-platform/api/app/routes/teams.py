from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..db import get_pool
from ..auth import hash_password, verify_password, create_team_token

router = APIRouter(prefix="/teams", tags=["teams"])

class RegisterIn(BaseModel):
    event_id: str
    team_name: str
    password: str
    email: str | None = None  # required in closed-registration mode


def _clean_email(email: str | None) -> str | None:
    return email.strip().lower() if email else None


class LoginIn(BaseModel):
    event_id: str
    team_name: str
    password: str

@router.post("/register")
async def register(body: RegisterIn):
    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT registration_mode FROM events WHERE id=$1", body.event_id
        )
        if not event:
            raise HTTPException(404, "no such event")

        email = _clean_email(body.email)
        async with conn.transaction():
            if event["registration_mode"] == "closed":
                if not email:
                    raise HTTPException(400, "registration is closed for this event — provide the invited email")
                if "@" not in email:
                    raise HTTPException(400, "email doesn't look like an email")
            existing = await conn.fetchrow(
                "SELECT id FROM teams WHERE event_id=$1 AND name=$2", body.event_id, body.team_name
            )
            if existing:
                raise HTTPException(409, "team name already taken for this event")
            row = await conn.fetchrow(
                "INSERT INTO teams (event_id, name, password_hash) VALUES ($1, $2, $3) RETURNING id",
                body.event_id, body.team_name, hash_password(body.password),
            )
            if event["registration_mode"] == "closed":
                # Atomic claim: only an unclaimed roster entry can be taken,
                # so two racers can't both walk off with the same invite.
                claimed = await conn.execute(
                    """
                    UPDATE roster SET claimed_by_team_id=$1
                    WHERE event_id=$2 AND email=$3 AND claimed_by_team_id IS NULL
                    """,
                    row["id"], body.event_id, email,
                )
                if claimed == "UPDATE 0":
                    raise HTTPException(
                        403, "that email is not on this event's roster, or it was already used by another team"
                    )
        token = create_team_token(str(row["id"]), body.event_id)
        return {"token": token, "team_id": str(row["id"])}

@router.post("/login")
async def login(body: LoginIn):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash FROM teams WHERE event_id=$1 AND name=$2",
            body.event_id, body.team_name,
        )
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "bad team name or password")
        token = create_team_token(str(row["id"]), body.event_id)
        return {"token": token, "team_id": str(row["id"])}
