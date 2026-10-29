"""
Participant accounts, organized around the organizer's invite roster.

The admin pastes invited emails into the roster (see admin.py). A participant
opens the workspace, types that email plus a password of their choosing, and
POST /users/signup creates their account, claims the roster entry, and gives
them a personal team — so a leaderboard row is one participant by default.
Joining a group is optional and still goes through the team endpoints;
team-scoped routes (submissions, results) accept a user token unchanged.

Login accepts the roster email (or, for older accounts, the username).
"""
import secrets
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..db import get_pool
from ..auth import (
    hash_password, verify_password, create_user_token, get_current_user,
)
from .events import event_status

router = APIRouter(prefix="/users", tags=["users"])

MIN_PASSWORD = 8


def _clean_email(raw: str | None) -> str | None:
    email = (raw or "").strip().lower().removeprefix("mailto:")
    return email if email and "@" in email else None


async def _pick_event(conn, email: str | None):
    """Which event an email belongs to. A roster entry wins over timing, so
    someone added to next week's roster doesn't land in today's other event;
    otherwise prefer running, then next to start, then most recently ended."""
    rows = await conn.fetch("SELECT * FROM events")
    if not rows:
        return None
    rostered = {
        str(r["event_id"])
        for r in await conn.fetch("SELECT event_id FROM roster WHERE email=$1", email)
    } if email else set()
    now = datetime.now(timezone.utc)

    def sort_key(row):
        status = event_status(row["start_at"], row["end_at"])
        if status == "running":
            timing = (0, 0.0)
        elif status == "not_started":
            timing = (1, (row["start_at"] - now).total_seconds())
        else:
            timing = (2, (now - row["end_at"]).total_seconds())
        return (0 if str(row["id"]) in rostered else 1, *timing)

    return min(rows, key=sort_key)


async def _unique_team_name(conn, event_id, wanted: str) -> str:
    """Teams are unique per event; two participants both defaulting to 'alex'
    should not block each other's signup."""
    base = wanted.strip()[:60] or "participant"
    name, n = base, 1
    while await conn.fetchval(
        "SELECT 1 FROM teams WHERE event_id=$1 AND lower(name)=lower($2)", event_id, name
    ):
        n += 1
        name = f"{base} ({n})"
    return name


class UserSignupIn(BaseModel):
    email: str
    password: str
    display_name: str | None = None   # optional; defaults to the email local part


class UserLoginIn(BaseModel):
    password: str
    login: str | None = None      # email (preferred) or legacy username
    username: str | None = None   # kept so old clients keep working


class UserRegisterIn(BaseModel):
    """Keep the team-based path for people who explicitly join a friend's team."""
    event_id: str
    team_name: str
    team_password: str   # the team's shared password — proves membership
    username: str
    password: str
    email: str | None = None  # required in closed-registration mode


@router.post("/signup")
async def signup(body: UserSignupIn):
    email = _clean_email(body.email)
    if not email:
        raise HTTPException(400, "enter the email your organizer registered for you")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(400, f"password must be at least {MIN_PASSWORD} characters")

    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await _pick_event(conn, email)
        if not event:
            raise HTTPException(404, "no event has been created yet")
        event_id = str(event["id"])

        if event["registration_mode"] == "closed" and not await conn.fetchval(
            "SELECT 1 FROM roster WHERE event_id=$1 AND email=$2", event_id, email
        ):
            raise HTTPException(
                403,
                "that email is not on this event's participant list — ask the organizers to add it",
            )

        if await conn.fetchval("SELECT 1 FROM users WHERE lower(email)=$1 OR username=$1", email):
            raise HTTPException(409, "an account already exists for that email — sign in instead")

        display_name = (body.display_name or "").strip()[:60] or email.split("@")[0]

        async with conn.transaction():
            roster = await conn.fetchrow(
                "SELECT id, claimed_by_team_id FROM roster WHERE event_id=$1 AND email=$2",
                event_id, email,
            )
            # A roster email already tied to a team means a captain registered
            # that team with this email; they sign in as a member, not a new team.
            team_id = roster["claimed_by_team_id"] if roster else None
            if team_id:
                team_name = await conn.fetchval("SELECT name FROM teams WHERE id=$1", team_id)
            else:
                team_name = await _unique_team_name(conn, event_id, display_name)
                team_id = await conn.fetchval(
                    """
                    INSERT INTO teams (event_id, name, password_hash)
                    VALUES ($1, $2, $3) RETURNING id
                    """,
                    # Personal team: nobody logs in as the team, so the shared
                    # password is discarded random bytes.
                    event_id, team_name, hash_password(secrets.token_urlsafe(32)),
                )
                if roster:
                    claimed = await conn.execute(
                        """
                        UPDATE roster SET claimed_by_team_id=$1
                        WHERE id=$2 AND claimed_by_team_id IS NULL
                        """,
                        team_id, roster["id"],
                    )
                    if claimed == "UPDATE 0":
                        raise HTTPException(409, "that invitation was just claimed — try signing in")

            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (username, password_hash, team_id, email, display_name)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    email, hash_password(body.password), team_id, email, display_name,
                )
            except asyncpg.UniqueViolationError:
                raise HTTPException(409, "an account already exists for that email — sign in instead")

        token = create_user_token(str(row["id"]), str(team_id), event_id, email)
        return {
            "token": token,
            "user_id": str(row["id"]),
            "team_id": str(team_id),
            "team_name": team_name,
            "event_id": event_id,
            "display_name": display_name,
        }


@router.post("/login")
async def login(body: UserLoginIn):
    ident = (body.login or body.username or "").strip()
    if not ident:
        raise HTTPException(400, "enter your email")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, u.team_id, u.username, u.display_name, u.password_hash,
                   t.event_id, t.name AS team_name, e.start_at, e.end_at
            FROM users u
            JOIN teams t ON t.id = u.team_id
            JOIN events e ON e.id = t.event_id
            WHERE lower(u.email) = lower($1) OR u.username = $1
            """,
            ident,
        )
    if not rows:
        raise HTTPException(404, "no account for that email yet — create it first")

    # Same email in more than one event: prefer the running one, then the
    # newest. Only the account whose password matches is accepted.
    now = datetime.now(timezone.utc)
    rows = sorted(
        rows,
        key=lambda r: (
            event_status(r["start_at"], r["end_at"]) != "running",
            -(r["start_at"] - now).total_seconds(),
        ),
    )
    for row in rows:
        if verify_password(body.password, row["password_hash"]):
            token = create_user_token(
                str(row["id"]), str(row["team_id"]), str(row["event_id"]), row["username"]
            )
            return {
                "token": token,
                "user_id": str(row["id"]),
                "team_id": str(row["team_id"]),
                "team_name": row["team_name"],
                "event_id": str(row["event_id"]),
                "display_name": row["display_name"],
            }
    raise HTTPException(401, "wrong password")


@router.post("/register")
async def register(body: UserRegisterIn):
    """Join an existing team with its shared password (optional group play)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchrow(
            "SELECT id, password_hash FROM teams WHERE event_id=$1 AND name=$2",
            body.event_id, body.team_name,
        )
        if not team or not verify_password(body.team_password, team["password_hash"]):
            raise HTTPException(401, "bad team name or password")
        mode = await conn.fetchval("SELECT registration_mode FROM events WHERE id=$1", body.event_id)
        email = _clean_email(body.email)
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
                "SELECT 1 FROM users u JOIN teams t ON t.id=u.team_id WHERE t.event_id=$1 AND u.email=$2",
                body.event_id, email,
            )
            if taken:
                raise HTTPException(409, "email already registered for a user in this event")
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, password_hash, team_id, email, display_name)
                VALUES ($1, $2, $3, $4, $5) RETURNING id
                """,
                body.username, hash_password(body.password), team["id"], email, body.username,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "username already taken")
        token = create_user_token(str(row["id"]), str(team["id"]), body.event_id, body.username)
        return {"token": token, "user_id": str(row["id"]), "team_id": str(team["id"])}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """Who am I, which team, and who else is on it."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchrow("SELECT name FROM teams WHERE id=$1", user["team_id"])
        members = await conn.fetch(
            "SELECT username, display_name, created_at FROM users WHERE team_id=$1 ORDER BY created_at",
            user["team_id"],
        )
        return {
            "username": user["sub"],
            "user_id": user["user_id"],
            "team_id": user["team_id"],
            "event_id": user["event_id"],
            "team_name": team["name"] if team else "?",
            "members": [
                {
                    "username": m["username"],
                    "display_name": m["display_name"],
                    "joined_at": m["created_at"].isoformat(),
                }
                for m in members
            ],
        }
