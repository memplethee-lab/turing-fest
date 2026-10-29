-- Hackfest platform schema
-- Written to be idempotent (IF NOT EXISTS throughout): scripts/apply_schema.py
-- re-runs it on every deploy, so Render/Neon provisioning needs no migration
-- tooling.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    freeze_at TIMESTAMPTZ,           -- leaderboard stops updating publicly after this (nullable = never freeze)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,     -- simple shared team login; swap for per-user auth later if needed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, name)
);

CREATE TABLE IF NOT EXISTS challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,              -- matches challenges/<slug> directory + image tag
    title TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 100,
    time_bonus_points INTEGER NOT NULL DEFAULT 0,  -- max bonus for an early solve, decays to 0 over the event
    editable_files TEXT[] NOT NULL,  -- filenames the team is allowed to submit
    briefing_md TEXT NOT NULL,       -- the "Phase 1 / Phase 2" writeup shown to teams
    UNIQUE (event_id, slug)
);

CREATE TABLE IF NOT EXISTS submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    files JSONB NOT NULL,            -- { "Freshness.ts": "...", "NonceStore.ts": "..." }
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | passed | failed | error
    checks JSONB,                    -- [{ "check": "...", "pass": true }, ...]
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    graded_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS solves (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    submission_id UUID NOT NULL REFERENCES submissions(id),
    points_awarded INTEGER NOT NULL,
    solved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (challenge_id, team_id)   -- first correct solve per team per challenge counts; resubmits don't double-score
);

CREATE INDEX IF NOT EXISTS idx_submissions_team ON submissions(team_id);
CREATE INDEX IF NOT EXISTS idx_submissions_challenge ON submissions(challenge_id);
CREATE INDEX IF NOT EXISTS idx_solves_team ON solves(team_id);

-- Per-admin accounts (replaces relying solely on the shared ADMIN_PASSWORD,
-- which now only bootstraps the initial "admin" user — see routes/admin.py).
CREATE TABLE IF NOT EXISTS admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user accounts. Each user belongs to exactly one team. A participant
-- invited by email (see roster below) signs up with that email and gets a
-- personal team, so a leaderboard row is one participant by default;
-- joining a group team is optional. Team-scoped endpoints accept a user's
-- token wherever they accept the team token.
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL,          -- the roster email; unique per event, see below
    password_hash TEXT NOT NULL,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    display_name TEXT,               -- what the leaderboard shows
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_team ON users(team_id);

-- Starting contents of each editable file, shown to teams in the workspace
-- editor. Seeded by admins with the challenge. Hidden test files must never
-- be added: this table is exactly what GET /api/challenges/{slug}/start
-- serves, so it only ever holds the team-facing vulnerable files.
CREATE TABLE IF NOT EXISTS challenge_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    UNIQUE (challenge_id, filename)
);
CREATE INDEX IF NOT EXISTS idx_challenge_files_challenge ON challenge_files(challenge_id);

-- Closed registration: the organizer pastes invited participants' emails here
-- (bulk). With events.registration_mode='closed', team and personal
-- registration must present an unclaimed email from this table; a team that
-- consumes an email keeps it reusable by its own members' accounts.
ALTER TABLE events ADD COLUMN IF NOT EXISTS registration_mode TEXT NOT NULL DEFAULT 'open';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;
CREATE INDEX IF NOT EXISTS idx_users_email ON users (lower(email));

-- A participant can be invited to several events, and the workspace makes them
-- pick one, so an account is one (email, event) pair: each membership gets its
-- own personal team and its own leaderboard row. Identity is the email, which
-- means the old global UNIQUE(username) has to go — uniqueness is per event.
ALTER TABLE users ADD COLUMN IF NOT EXISTS event_id UUID REFERENCES events(id) ON DELETE CASCADE;
UPDATE users u SET event_id = t.event_id
  FROM teams t
 WHERE t.id = u.team_id AND u.event_id IS DISTINCT FROM t.event_id;
CREATE INDEX IF NOT EXISTS idx_users_event ON users(event_id);
DO $$
DECLARE con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
         WHERE c.conrelid = 'users'::regclass AND c.contype = 'u' AND a.attname = 'username'
    LOOP
        EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_event ON users (lower(email), event_id);

CREATE TABLE IF NOT EXISTS roster (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    email TEXT NOT NULL,             -- normalized: lowercased, trimmed
    claimed_by_team_id UUID REFERENCES teams(id),  -- team that consumed the invite (NULL = unused)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, email)
);
CREATE INDEX IF NOT EXISTS idx_roster_event ON roster(event_id);
