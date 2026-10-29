import asyncpg
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..db import get_pool
from ..auth import (
    hash_password, verify_password, create_user_token, get_current_user,
)

router = APIRouter(prefix="/users", tags=["users"])


class UserRegisterIn(BaseModel):
    event_id: str
    team_name: str
    team_password: str   # the team's shared password — proves membership
    username: str
    password: str
    email: str | None = None  # required in closed-registration mode


class UserLoginIn(BaseModel):
    event_id: str
    email: str | None = None
    username: str | None = None
    password: str


@router.post("/register")
async def register(body: UserRegisterIn):
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchrow(
            "SELECT id, password_hash FROM teams WHERE event_id=$1 AND name=$2",
            body.event_id, body.team_name,
        )
        if not team or not verify_password(body.team_password, team["password_hash"]):
            raise HTTPException(401, "bad team name or password")
        mode = await conn.fetchval("SELECT registration_mode FROM events WHERE id=$1", body.event_id)
        email = body.email.strip().lower() if body.email else None
        if mode == "closed":
            if not email:
                raise HTTPException(400, "registration is closed for this event — provide your invited email")
            claimed = await conn.execute(
                """
                UPDATE roster SET claimed_by_team_id=$1
                WHERE event_id=$2 AND email=$3
                  AND (claimed_by_team_id IS NULL OR claimed_by_team_id=$1)
                """,
                team["id"], body.event_id, email,
            )
            if claimed == "UPDATE 0":
                raise HTTPException(
                    403, "that email is not on this event's roster, or it was already used by a different team"
                )
            taken = await conn.fetchval(
                """
                SELECT 1 FROM users u JOIN teams t ON t.id=u.team_id
                WHERE t.event_id=$1 AND u.email=$2
                """,
                body.event_id, email,
            )
            if taken:
                raise HTTPException(409, "email already registered for a user in this event")
        try:
            row = await conn.fetchrow(
                "INSERT INTO users (username, password_hash, team_id, email) VALUES ($1, $2, $3, $4) RETURNING id",
                body.username, hash_password(body.password), team["id"], email,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "username already taken")
        token = create_user_token(str(row["id"]), str(team["id"]), body.event_id, body.username)
        return {"token": token, "user_id": str(row["id"]), "team_id": str(team["id"]) }


@router.post("/login")
async def login(body: UserLoginIn):
    if not body.event_id:
        raise HTTPException(400, "event_id is required")
    identifier = (body.email or body.username or "").strip()
    if not identifier:
        raise HTTPException(400, "email or username is required")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if body.email:
            invited = await conn.fetchval(
                "SELECT 1 FROM roster WHERE event_id=$1 AND LOWER(email) = LOWER($2)",
                body.event_id,
                body.email.strip().lower(),
            )
            if not invited:
                raise HTTPException(403, "this email is not on the event roster")
            row = await conn.fetchrow(
                """
                SELECT u.id, u.team_id, t.event_id, u.password_hash, u.username, u.email
                FROM users u JOIN teams t ON t.id = u.team_id
                WHERE t.event_id = $1
                  AND LOWER(COALESCE(u.email, '')) = LOWER($2)
                """,
                body.event_id, body.email.strip().lower(),
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT u.id, u.team_id, t.event_id, u.password_hash, u.username, u.email
                FROM users u JOIN teams t ON t.id = u.team_id
                WHERE t.event_id = $1
                  AND LOWER(u.username) = LOWER($2)
                """,
                body.event_id, identifier,
            )
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "bad participant email or password")
        token = create_user_token(str(row["id"]), str(row["team_id"]), str(row["event_id"]), row["username"])
        return {"token": token, "user_id": str(row["id"]), "team_id": str(row["team_id"])}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """Who am I, which team, and who else is on it."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchrow("SELECT name FROM teams WHERE id=$1", user["team_id"])
        members = await conn.fetch(
            "SELECT username, created_at FROM users WHERE team_id=$1 ORDER BY created_at",
            user["team_id"],
        )
        return {
            "username": user["sub"],
            "user_id": user["user_id"],
            "team_id": user["team_id"],
            "event_id": user["event_id"],
            "team_name": team["name"] if team else "?",
            "members": [{"username": m["username"], "joined_at": m["created_at"].isoformat()} for m in members],
        }
