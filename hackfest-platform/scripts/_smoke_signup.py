"""Live smoke test for the email-first participant flow against the real DB.

Creates a throwaway closed event ("_signup-smoke-test") with one roster email,
walks signup/login/me through the real ASGI app, then deletes the event
(cascading to its team, user and roster rows). Safe to re-run.
"""
import asyncio
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent

# --- env: use the repo .env (Neon) so this exercises the same DB as deploy ---
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.strip())
os.environ.setdefault("JWT_SECRET", "smoke-jwt-secret")
os.environ.setdefault("FLAG_SECRET", "smoke-flag-secret")
os.environ.setdefault("ADMIN_PASSWORD", "smoke-admin-pass")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(ROOT / "api"))
from app.main import app  # noqa: E402

DB = os.environ["DATABASE_URL"]
EVENT_NAME = "_signup-smoke-test"
EMAIL = "smoke.participant@example.com"
PASSWORD = "sm0ke-pass-123"


async def setup() -> str:
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute("DELETE FROM events WHERE name=$1", EVENT_NAME)
        now = datetime.now(timezone.utc)
        event_id = await conn.fetchval(
            """
            INSERT INTO events (name, start_at, end_at, registration_mode)
            VALUES ($1, $2, $3, 'closed') RETURNING id
            """,
            EVENT_NAME, now - timedelta(hours=1), now + timedelta(hours=1),
        )
        await conn.execute(
            "INSERT INTO roster (event_id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            event_id, EMAIL,
        )
        return str(event_id)
    finally:
        await conn.close()


async def inspect(event_id: str) -> dict:
    conn = await asyncpg.connect(DB)
    try:
        claimed = await conn.fetchval(
            "SELECT claimed_by_team_id IS NOT NULL FROM roster WHERE event_id=$1 AND email=$2",
            event_id, EMAIL,
        )
        user = await conn.fetchrow(
            """
            SELECT u.email, u.display_name, u.username, t.name AS team_name
            FROM users u JOIN teams t ON t.id = u.team_id
            WHERE t.event_id=$1 AND u.email=$2
            """,
            event_id, EMAIL,
        )
        # exact leaderboard query from routes/leaderboard.py, to prove it runs
        board = await conn.fetch(
            """
            SELECT t.id, t.name, COUNT(u.id) AS members
            FROM teams t
            LEFT JOIN users u ON u.team_id = t.id
            WHERE t.event_id = $1
            GROUP BY t.id, t.name
            """,
            event_id,
        )
        return {
            "claimed": claimed,
            "user": dict(user) if user else None,
            "board": [dict(r) for r in board],
        }
    finally:
        await conn.close()


async def cleanup(event_id: str) -> int:
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute("DELETE FROM events WHERE id=$1", event_id)
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE email=$1", EMAIL)
    finally:
        await conn.close()


def check(label: str, got: int, want: int) -> None:
    print(f"{'ok  ' if got == want else 'FAIL'} {label}: {got} (want {want})")
    assert got == want, f"{label}: got {got}, want {want}"


with TestClient(app) as client:      # startup runs the idempotent schema bootstrap
    event_id = asyncio.run(setup())
    print("temp event:", event_id)
    try:
        current = client.get("/events/current")
        print("events/current:", current.status_code, current.json().get("name"))

        signup = client.post("/users/signup", json={
            "email": EMAIL.upper(),           # normalization: upper-case input
            "password": PASSWORD,
            "display_name": "Smoke Tester",
        })
        check("signup", signup.status_code, 200)
        token = signup.json()["token"]
        print("signup team:", signup.json()["team_name"])

        me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        check("users/me", me.status_code, 200)
        check("me team members", len(me.json()["members"]), 1)

        ready = client.get("/challenges", headers={"Authorization": f"Bearer {token}"})
        check("challenges with user token", ready.status_code, 200)

        login = client.post("/users/login", json={"login": EMAIL, "password": PASSWORD})
        check("login", login.status_code, 200)

        legacy = client.post("/users/login", json={"username": EMAIL, "password": PASSWORD})
        check("legacy username field", legacy.status_code, 200)

        wrong = client.post("/users/login", json={"login": EMAIL, "password": "wrong-password"})
        check("login wrong password", wrong.status_code, 401)

        dup = client.post("/users/signup", json={"email": EMAIL, "password": PASSWORD})
        check("duplicate signup", dup.status_code, 409)

        outsider = client.post("/users/signup", json={
            "email": "not.invited@example.com", "password": PASSWORD,
        })
        check("non-roster signup on closed event", outsider.status_code, 403)
        print("   message:", outsider.json().get("detail"))

        short = client.post("/users/signup", json={"email": "x@example.com", "password": "short"})
        check("short password", short.status_code, 400)

        state = asyncio.run(inspect(event_id))
        assert state["claimed"] is True, "roster email was not claimed"
        assert state["user"] is not None, "user row missing"
        assert state["user"]["email"] == EMAIL, state["user"]
        assert state["user"]["display_name"] == "Smoke Tester", state["user"]
        assert len(state["board"]) == 1 and state["board"][0]["members"] == 1, state["board"]
        print("db state:", state["user"], "| board:", state["board"])
    finally:
        remaining = asyncio.run(cleanup(event_id))
        check("cleanup (users left with test email)", remaining, 0)

print("ALL CHECKS PASSED")
