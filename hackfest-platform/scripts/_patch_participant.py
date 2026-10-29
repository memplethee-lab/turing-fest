"""One-off textual patch for the roster/email participant flow.

SearchReplace refuses these files even though the bytes match, so apply the
edits here. Delete this file once it has run.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def patch(rel: str, pairs: list[tuple[str, str]]) -> None:
    path = ROOT / rel
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    for old, new in pairs:
        assert text.count(old) == 1, f"{rel}: expected exactly one match for {old[:60]!r} (got {text.count(old)})"
        text = text.replace(old, new)
    path.write_bytes(text.encode("utf-8"))
    print(f"patched {rel}")


patch("db/schema.sql", [
    (
        "-- Per-user accounts. Each user belongs to exactly one team; team membership\n"
        "-- is proven at registration with the team's shared password. Team-scoped\n"
        "-- endpoints accept a user's token wherever they accept the team token.\n"
        "CREATE TABLE IF NOT EXISTS users (\n"
        "    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
        "    username TEXT NOT NULL UNIQUE,\n"
        "    password_hash TEXT NOT NULL,\n"
        "    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,\n"
        "    created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n"
        ");",
        "-- Per-user accounts. Each user belongs to exactly one team. A participant\n"
        "-- invited by email (see roster below) signs up with that email and gets a\n"
        "-- personal team, so a leaderboard row is one participant by default;\n"
        "-- joining a group team is optional. Team-scoped endpoints accept a user's\n"
        "-- token wherever they accept the team token.\n"
        "CREATE TABLE IF NOT EXISTS users (\n"
        "    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
        "    username TEXT NOT NULL UNIQUE,   -- the roster email: unambiguous login id\n"
        "    password_hash TEXT NOT NULL,\n"
        "    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,\n"
        "    display_name TEXT,               -- what the leaderboard shows\n"
        "    created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n"
        ");",
    ),
    (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;\n"
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;\n"
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users (lower(email));",
    ),
])

patch("api/app/routes/admin.py", [
    (
        '"status": (f"team: {r[\'team_name\']}" if r["claimed_by_team_id"] else "unused"),',
        '"status": (f"registered: {r[\'team_name\']}" if r["claimed_by_team_id"] else "unused"),',
    ),
])
