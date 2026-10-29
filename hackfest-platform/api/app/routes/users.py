"""
Participant accounts, organized around the organizer's invite roster.

The admin pastes invited emails into the roster (see admin.py). A participant
opens the workspace, signs in with that email plus a password of their choice,
and is then shown the events they can take part in — the one running now first
— and picks one. Nobody ever types an event id.

An account is one (email, event) pair, each with its own personal team, so a
leaderboard row is one participant by default. The invite itself is the person's
passport, not a single event: an email on *any* roster may enter every event and
browse past ones. Joining a group team is optional and still goes through the
team endpoints; team-scoped routes (submissions, results) accept a user token
unchanged.

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

# What a participant scans first: what is running, then what starts next, then
# what just finished.
EVENT_ORDER = {"running": 0, "not_started": 1, "ended": 2}


def _clean_email(raw: str | None) -> str | None:
    email = (raw or "").strip().lower().removeprefix("mailto:")
    return email if email and "@" in email else None


async def _invited_anywhere(conn, key: str) -> bool:
    """Is this email on any event's participant list? Rosters are per event, but
    an invite makes someone a participant of the whole hackfest: they may then
    enter any event, including ones they were not individually added to."""
    return bool(await conn.fetchval(
        "SELECT 1 FROM roster WHERE lower(email)=lower($1) LIMIT 1", key
    ))


async def _pick_event(conn, email: str | None):
    """Which event a brand-new account starts in: the one running now, then the
    next to start, then the most recently ended. Timing leads, because an invite
    is the person's passport to every event — but when two events are equally
    live, the one that named this email on its roster wins. Only a default: the
    workspace lists everything they can reach and lets them choose
    (POST /users/events/{id}/enter)."""
    rows = await conn.fetch("SELECT * FROM events")
    if not rows:
        return None
    rostered = {
        str(r["event_id"])
        for r in await conn.fetch("SELECT event_id FROM roster WHERE lower(email)=lower($1)", email)
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
        return (*timing, 0 if str(row["id"]) in rostered else 1, str(row["id"]))

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


async def _identity(conn, user):
    """The signed-in participant's own row; the email is the identity that spans
    events, so it is what the event list and 'enter event' key off."""
    return await conn.fetchrow(
        "SELECT id, username, email, display_name, password_hash FROM users WHERE id=$1",
        user["user_id"],
    )


def _ident_key(ident) -> str:
    return _clean_email(ident["email"]) or ident["username"]


async def _memberships(conn, key: str) -> dict[str, dict]:
    """event_id -> the account this email already has there."""
    rows = await conn.fetch(
        """
        SELECT u.id, u.team_id, u.display_name, t.name AS team_name, t.event_id
        FROM users u
        JOIN teams t ON t.id = u.team_id
        WHERE lower(u.email) = lower($1) OR u.username = $1
        """,
        key,
    )
    out = {}
    for r in rows:
        out[str(r["event_id"])] = {
            "user_id": str(r["id"]),
            "team_id": str(r["team_id"]),
            "team_name": r["team_name"],
            "display_name": r["display_name"],
        }
    return out


async def _event_choices(conn, key: str) -> list[dict]:
    """Everything this participant can reach, in the order they scan it: running
    first, then what starts next, then what just finished. An invited email sees
    the whole programme — open events, other people's closed events and past ones
    (whose leaderboards stay readable) — because the invite belongs to the person,
    not to one event. Only closed events are hidden from someone with no invite at
    all, which is what keeps a private event private."""
    events = await conn.fetch(
        "SELECT id, name, start_at, end_at, registration_mode FROM events"
    )
    if not events:
        return []
    rostered = {
        str(r["event_id"])
        for r in await conn.fetch("SELECT event_id FROM roster WHERE lower(email)=lower($1)", key)
    }
    guest = await _invited_anywhere(conn, key)
    mine = await _memberships(conn, key)
    now = datetime.now(timezone.utc)

    def sort_key(row):
        status = event_status(row["start_at"], row["end_at"])
        if status == "not_started":
            timing = (row["start_at"] - now).total_seconds()
        elif status == "ended":
            timing = (now - row["end_at"]).total_seconds()
        else:
            timing = 0.0
        return (
            EVENT_ORDER[status],
            timing,
            # Two events equally live: the one that named this email on its own
            # roster is offered first, matching the event signup defaults to.
            0 if str(row["id"]) in rostered else 1,
            str(row["id"]),
        )

    choices = []
    for row in sorted(events, key=sort_key):
        event_id = str(row["id"])
        status = event_status(row["start_at"], row["end_at"])
        joined = mine.get(event_id)
        invited_here = event_id in rostered
        can_enter = bool(joined) or guest or invited_here or row["registration_mode"] != "closed"
        if not can_enter:
            continue      # a closed event this person has no invite for at all
        choices.append({
            "id": event_id,
            "name": row["name"],
            "start_at": row["start_at"].isoformat(),
            "end_at": row["end_at"].isoformat(),
            "status": status,
            "registration_mode": row["registration_mode"],
            "invited": guest or invited_here,
            "invited_here": invited_here,
            "joined": bool(joined),
            "team_name": joined["team_name"] if joined else None,
            "can_enter": can_enter,
            # Past events stay in the list for their results, but the clock has
            # run out: the workspace links to the leaderboard instead of opening
            # the editor (the API rejects submissions once the event has ended).
            "accepts_submissions": status == "running",
        })
    return choices


def _session(ident, user_id: str, team_id: str, event, team_name: str, display_name: str) -> dict:
    """Token + the event it is scoped to, in the shape the workspace expects."""
    event_id = str(event["id"])
    return {
        "token": create_user_token(user_id, team_id, event_id, ident["username"]),
        "user_id": user_id,
        "team_id": team_id,
        "team_name": team_name,
        "event_id": event_id,
        "event_name": event["name"],
        "event_status": event_status(event["start_at"], event["end_at"]),
        "display_name": display_name,
    }


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
        if await conn.fetchval(
            "SELECT 1 FROM users WHERE lower(email)=$1 OR username=$1", email
        ):
            raise HTTPException(409, "an account already exists for that email — sign in instead")

        event = await _pick_event(conn, email)
        if not event:
            raise HTTPException(404, "no event has been created yet")
        event_id = str(event["id"])

        if event["registration_mode"] == "closed" and not await _invited_anywhere(conn, email):
            raise HTTPException(
                403,
                "that email is not on the participant list — ask the organizers to add it",
            )

        display_name = (body.display_name or "").strip()[:60] or email.split("@")[0]

        async with conn.transaction():
            roster = await conn.fetchrow(
                "SELECT id, claimed_by_team_id FROM roster WHERE event_id=$1 AND lower(email)=lower($2)",
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
                    INSERT INTO users (username, password_hash, team_id, email, display_name, event_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    email, hash_password(body.password), team_id, email, display_name, event_id,
                )
            except asyncpg.UniqueViolationError:
                raise HTTPException(409, "an account already exists for that email — sign in instead")

        payload = _session({"username": email}, str(row["id"]), str(team_id), event, team_name, display_name)
        payload["events"] = await _event_choices(conn, email)
        return payload


@router.post("/login")
async def login(body: UserLoginIn):
    ident = (body.login or body.username or "").strip()
    if not ident:
        raise HTTPException(400, "enter your email")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, u.team_id, u.username, u.email, u.display_name, u.password_hash,
                   t.name AS team_name, t.event_id,
                   e.id AS ev_id, e.name AS event_name, e.start_at, e.end_at
            FROM users u
            JOIN teams t ON t.id = u.team_id
            JOIN events e ON e.id = t.event_id
            WHERE lower(u.email) = lower($1) OR u.username = $1
            """,
            ident,
        )
        if not rows:
            raise HTTPException(404, "no account for that email yet — create it first")

        # One account per (email, event): hand them the token for the event they
        # can play in right now, then the next to start, then the most recent one
        # to finish — the same scan order the picker uses. Only a membership
        # whose password matches is accepted.
        now = datetime.now(timezone.utc)

        def login_key(r):
            status = event_status(r["start_at"], r["end_at"])
            timing = (r["start_at"] or now) - now
            return (
                EVENT_ORDER[status],
                timing if status == "not_started" else -timing,
            )

        rows = sorted(rows, key=login_key)
        for row in rows:
            if not verify_password(body.password, row["password_hash"]):
                continue
            key = _clean_email(row["email"]) or row["username"]
            event = {"id": row["ev_id"], "name": row["event_name"], "start_at": row["start_at"], "end_at": row["end_at"]}
            payload = _session(
                {"username": row["username"]}, str(row["id"]), str(row["team_id"]),
                event, row["team_name"], row["display_name"] or key,
            )
            payload["events"] = await _event_choices(conn, key)
            return payload

    raise HTTPException(401, "wrong password")


@router.get("/events")
async def my_events(user=Depends(get_current_user)):
    """The events this participant can take part in — what the workspace's
    event picker lists (running event first)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        ident = await _identity(conn, user)
        if not ident:
            raise HTTPException(401, "sign in again")
        return {"events": await _event_choices(conn, _ident_key(ident))}


@router.post("/events/{event_id}/enter")
async def enter_event(event_id: str, user=Depends(get_current_user)):
    """Pick the event to take part in. Reuses the account and team this person
    already has there; on a first visit claims their roster invite and creates
    the personal team, carrying the password hash over from their account."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        ident = await _identity(conn, user)
        if not ident:
            raise HTTPException(401, "sign in again")
        key = _ident_key(ident)

        event = await conn.fetchrow(
            "SELECT id, name, start_at, end_at, registration_mode FROM events WHERE id=$1",
            event_id,
        )
        if not event:
            raise HTTPException(404, "no such event")

        existing = (await _memberships(conn, key)).get(event_id)
        if existing:
            return _session(
                ident, existing["user_id"], existing["team_id"], event,
                existing["team_name"], existing["display_name"] or key,
            )

        display_name = (ident["display_name"] or "").strip()[:60] or key.split("@")[0]
        async with conn.transaction():
            roster = await conn.fetchrow(
                "SELECT id, claimed_by_team_id FROM roster WHERE event_id=$1 AND lower(email)=lower($2)",
                event_id, key,
            )
            # Any invite unlocks any event; roster=None just means no invite to
            # claim here, so they get a plain personal team.
            if event["registration_mode"] == "closed" and not roster \
                    and not await _invited_anywhere(conn, key):
                raise HTTPException(
                    403,
                    "you are not on the participant list — ask the organizers to add your email",
                )
            team_id = roster["claimed_by_team_id"] if roster else None
            if team_id:
                team_name = await conn.fetchval("SELECT name FROM teams WHERE id=$1", team_id)
            else:
                team_name = await _unique_team_name(conn, event_id, display_name)
                team_id = await conn.fetchval(
                    "INSERT INTO teams (event_id, name, password_hash) VALUES ($1, $2, $3) RETURNING id",
                    event_id, team_name, hash_password(secrets.token_urlsafe(32)),
                )
                if roster:
                    claimed = await conn.execute(
                        "UPDATE roster SET claimed_by_team_id=$1 WHERE id=$2 AND claimed_by_team_id IS NULL",
                        team_id, roster["id"],
                    )
                    if claimed == "UPDATE 0":
                        raise HTTPException(409, "that invitation was just claimed — try again")

            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (username, password_hash, team_id, email, display_name, event_id)
                    VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                    """,
                    key, ident["password_hash"], team_id, key, display_name, event_id,
                )
            except asyncpg.UniqueViolationError:
                # Two tabs entering at once: the other one already created it.
                row = await conn.fetchrow(
                    "SELECT id, team_id, display_name FROM users WHERE event_id=$1 AND lower(email)=lower($2)",
                    event_id, key,
                )
                if not row:
                    raise HTTPException(409, "could not create your account for that event — try again")
                team_id, display_name = row["team_id"], row["display_name"] or display_name
                team_name = await conn.fetchval("SELECT name FROM teams WHERE id=$1", team_id)

        return _session(ident, str(row["id"]), str(team_id), event, team_name, display_name)


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
                WHERE event_id=$2 AND lower(email)=lower($3)
                  AND (claimed_by_team_id IS NULL OR claimed_by_team_id=$1)
                """,
                team["id"], body.event_id, email,
            )
            if claimed == "UPDATE 0":
                raise HTTPException(
                    403, "that email is not on this event's roster, or it was already used by a different team"
                )
            taken = await conn.fetchval(
                "SELECT 1 FROM users u JOIN teams t ON t.id=u.team_id WHERE t.event_id=$1 AND lower(u.email)=lower($2)",
                body.event_id, email,
            )
            if taken:
                raise HTTPException(409, "email already registered for a user in this event")
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, password_hash, team_id, email, display_name, event_id)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """,
                body.username, hash_password(body.password), team["id"], email, body.username,
                body.event_id,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "that email is already registered for this event")
        token = create_user_token(str(row["id"]), str(team["id"]), body.event_id, body.username)
        return {"token": token, "user_id": str(row["id"]), "team_id": str(team["id"])}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """Who am I, which team and event, and who else is on the team."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.username, u.display_name, e.name AS event_name, e.start_at, e.end_at
            FROM users u JOIN events e ON e.id = u.event_id
            WHERE u.id = $1
            """,
            user["user_id"],
        )
        team = await conn.fetchrow("SELECT name FROM teams WHERE id=$1", user["team_id"])
        members = await conn.fetch(
            "SELECT display_name, created_at FROM users WHERE team_id=$1 ORDER BY created_at",
            user["team_id"],
        )
        event = None
        if row:
            event = {"name": row["event_name"], "status": event_status(row["start_at"], row["end_at"])}
        return {
            "username": user["sub"],
            "user_id": user["user_id"],
            "team_id": user["team_id"],
            "event_id": user["event_id"],
            "team_name": team["name"] if team else "?",
            "display_name": (row["display_name"] if row else None) or user["sub"],
            "event": event,
            "members": [
                {
                    "display_name": m["display_name"],
                    "joined_at": m["created_at"].isoformat(),
                }
                for m in members
            ],
        }
