-- Hackfest platform schema

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    freeze_at TIMESTAMPTZ,           -- leaderboard stops updating publicly after this (nullable = never freeze)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,     -- simple shared team login; swap for per-user auth later if needed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, name)
);

CREATE TABLE challenges (
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

CREATE TABLE submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    files JSONB NOT NULL,            -- { "Freshness.ts": "...", "NonceStore.ts": "..." }
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | passed | failed | error
    checks JSONB,                    -- [{ "check": "...", "pass": true }, ...]
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    graded_at TIMESTAMPTZ
);

CREATE TABLE solves (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    submission_id UUID NOT NULL REFERENCES submissions(id),
    points_awarded INTEGER NOT NULL,
    solved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (challenge_id, team_id)   -- first correct solve per team per challenge counts; resubmits don't double-score
);

CREATE INDEX idx_submissions_team ON submissions(team_id);
CREATE INDEX idx_submissions_challenge ON submissions(challenge_id);
CREATE INDEX idx_solves_team ON solves(team_id);
