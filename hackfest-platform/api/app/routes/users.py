"""
Per-user accounts layered on top of teams.

Teams keep the shared name+password login (teams.py) — useful for scripting
and as the "team secret" members share to prove membership. On top of that,
individual users register with their own username/password attached to a
team; their JWT carries the same team_id/event_id claims, so every
team-scoped endpoint (submissions, results) accepts a user token unchanged.
Rate limits remain per-team by design (anti-starvation is a team-level
property).
"""
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


class UserLoginIn(BaseModel):
    username: str
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
        try:
            row = await conn.fetchrow(
                "INSERT INTO users (username, password_hash, team_id) VALUES ($1, $2, $3) RETURNING id",
                body.username, hash_password(body.password), team["id"],
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "username already taken")
        token = create_user_token(str(row["id"]), str(team["id"]), body.event_id, body.username)
        return {"token": token, "user_id": str(row["id"]), "team_id": str(team["id"])}


@router.post("/login")
async def login(body: UserLoginIn):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.id, u.team_id, t.event_id, u.password_hash
            FROM users u JOIN teams t ON t.id = u.team_id
            WHERE u.username = $1
            """,
            body.username,
        )
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "bad username or password")
        token = create_user_token(str(row["id"]), str(row["team_id"]), str(row["event_id"]), body.username)
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
