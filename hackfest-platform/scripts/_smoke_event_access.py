"""Live smoke test: an invited participant sees and can enter every event.

Four throwaway events — MAIN (running, invites the test email), OTHER (running,
closed, invites somebody else), NEXT (upcoming, open registration) and PAST
(ended, closed, invites somebody else) — plus one email with no invite at all.
Run against the real DB; deletes the events afterwards (cascades to accounts,
teams and roster rows), so it is safe to re-run.
"""
import asyncio
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent

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
EMAIL = "access.smoke@example.com"
STRANGER = "stranger.smoke@example.com"
PASSWORD = "4ccess-pass-123"
DISPLAY = "Access Smoke"
MAIN, OTHER, NEXT, PAST = "_access-smoke-main", "_access-smoke-other", "_access-smoke-next", "_access-smoke-past"
NAMES = [MAIN, OTHER, NEXT, PAST]

failures = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r} (want {want!r})")
    if not ok:
        failures.append(label)


async def setup() -> dict:
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute("DELETE FROM events WHERE name = ANY($1::text[])", NAMES)
        now = datetime.now(timezone.utc)

        async def add(name, start, end, mode, invited):
            event_id = await conn.fetchval(
                "INSERT INTO events (name, start_at, end_at, registration_mode) VALUES ($1,$2,$3,$4) RETURNING id",
                name, start, end, mode,
            )
            for email in invited:
                await conn.execute(
                    "INSERT INTO roster (event_id, email) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    event_id, email,
                )
            return str(event_id)

        return {
            "main": await add(MAIN, now - timedelta(hours=1), now + timedelta(hours=1), "closed", [EMAIL]),
            "other": await add(OTHER, now - timedelta(hours=1), now + timedelta(hours=1), "closed", [STRANGER]),
            "next": await add(NEXT, now + timedelta(days=2), now + timedelta(days=2, hours=6), "open", []),
            "past": await add(PAST, now - timedelta(days=3), now - timedelta(days=2), "closed", [STRANGER]),
        }
    finally:
        await conn.close()


async def inspect() -> dict:
    conn = await asyncpg.connect(DB)
    try:
        rows = await conn.fetch(
            """
            SELECT e.name AS event, t.name AS team, r.claimed_by_team_id
            FROM users u
            JOIN teams t ON t.id = u.team_id
            JOIN events e ON e.id = t.event_id
            LEFT JOIN roster r ON r.event_id = e.id AND lower(r.email) = lower($1)
            WHERE lower(u.email) = lower($1)
            ORDER BY e.name
            """,
            EMAIL,
        )
        return {
            "memberships": [r["event"] for r in rows],
            "teams": sorted({r["team"] for r in rows}),
            "claimed": {r["event"]: bool(r["claimed_by_team_id"]) for r in rows},
        }
    finally:
        await conn.close()


async def cleanup() -> int:
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute("DELETE FROM events WHERE name = ANY($1::text[])", NAMES)
        return await conn.fetchval(
            "SELECT count(*) FROM users WHERE lower(email) = ANY($1::text[])", [EMAIL, STRANGER]
        )
    finally:
        await conn.close()


def main() -> None:
    ids = asyncio.run(setup())
    print("events:", {k: v[:8] for k, v in ids.items()})
    try:
        with TestClient(app) as client:
            r = client.post("/users/signup", json={
                "email": EMAIL, "password": PASSWORD, "display_name": DISPLAY,
            })
            check("signup", r.status_code, 200)
            data = r.json()
            check("default event is the live one they were invited to", data["event_id"], ids["main"])
            mine = [e for e in data["events"] if e["id"] in ids.values()]
            by_id = {e["id"]: e for e in data["events"]}
            check("all four events listed", [e["id"] for e in mine],
                  [ids["main"], ids["other"], ids["next"], ids["past"]])
            check("listed in scan order", [by_id[e["id"]]["status"] for e in mine],
                  ["running", "running", "not_started", "ended"])
            check("invited to main", (by_id[ids["main"]]["invited"], by_id[ids["main"]]["invited_here"]), (True, True))
            check("closed event they were not added to is still visible",
                  (by_id[ids["other"]]["invited"], by_id[ids["other"]]["invited_here"], by_id[ids["other"]]["can_enter"]),
                  (True, False, True))
            check("past event visible for its results",
                  (by_id[ids["past"]]["status"], by_id[ids["past"]]["accepts_submissions"]), ("ended", False))
            check("open upcoming event visible", by_id[ids["next"]]["can_enter"], True)

            h = {"Authorization": f"Bearer {data['token']}"}

            r = client.post(f"/users/events/{ids['other']}/enter", headers=h)
            check("enter a closed event they were not individually invited to", r.status_code, 200)
            other = r.json()
            check("entered the other live event", other["event_id"], ids["other"])
            check("same personal team name", other["team_name"], DISPLAY)

            r = client.post(f"/users/events/{ids['past']}/enter", headers=h)
            check("open a past event", r.status_code, 200)
            check("past event is marked ended", r.json()["event_status"], "ended")
            past = r.json()

            r = client.get("/users/events", headers=h)
            check("list after entering", sorted(e["id"] for e in r.json()["events"] if e["id"] in ids.values()),
                  sorted(ids.values()))
            check("main now marked joined",
                  [e["joined"] for e in r.json()["events"] if e["id"] == ids["main"]], [True])

            past_h = {"Authorization": f"Bearer {past['token']}"}
            live_h = {"Authorization": f"Bearer {other['token']}"}
            body = {"challenge_slug": "does-not-exist", "files": {"Freshness.ts": "x"}}
            r = client.post("/submissions", headers=past_h, json=body)
            check("submissions refused in a past event", r.status_code, 403)
            print("   message:", r.json().get("detail"))
            r = client.post("/submissions", headers=live_h, json=body)
            check("live event token gets as far as the challenge lookup", r.status_code, 404)

            r = client.post("/users/login", json={"login": EMAIL, "password": PASSWORD})
            check("login", r.status_code, 200)
            check("login still offers every event",
                  sorted(e["id"] for e in r.json()["events"] if e["id"] in ids.values()), sorted(ids.values()))
            check("login lands on a live event", r.json()["event_id"] in {ids["main"], ids["other"]}, True)

            r = client.post("/users/signup", json={"email": STRANGER, "password": PASSWORD})
            check("a stranger on only-closed rosters can still sign up", r.status_code, 200)

            r = client.post("/users/signup", json={"email": "nobody.smoke@example.com", "password": PASSWORD})
            check("no invite anywhere on a closed event", r.status_code, 403)
            print("   message:", r.json().get("detail"))

        db = asyncio.run(inspect())
        check("memberships (one account per event entered)", db["memberships"], [MAIN, OTHER, PAST])
        check("personal team per membership", db["teams"], [DISPLAY])
        check("invite claimed only where they were on the list", db["claimed"], {MAIN: True, OTHER: False, PAST: False})
    finally:
        left = asyncio.run(cleanup())
        check("cleanup (accounts left)", left, 0)

    print("\nALL CHECKS PASSED" if not failures else f"\nFAILED: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
