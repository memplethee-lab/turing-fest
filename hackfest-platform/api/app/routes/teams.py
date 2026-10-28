from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..db import get_pool
from ..auth import hash_password, verify_password, create_team_token

router = APIRouter(prefix="/teams", tags=["teams"])

class RegisterIn(BaseModel):
    event_id: str
    team_name: str
    password: str

class LoginIn(BaseModel):
    event_id: str
    team_name: str
    password: str

@router.post("/register")
async def register(body: RegisterIn):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM teams WHERE event_id=$1 AND name=$2", body.event_id, body.team_name
        )
        if existing:
            raise HTTPException(409, "team name already taken for this event")
        row = await conn.fetchrow(
            "INSERT INTO teams (event_id, name, password_hash) VALUES ($1, $2, $3) RETURNING id",
            body.event_id, body.team_name, hash_password(body.password),
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
