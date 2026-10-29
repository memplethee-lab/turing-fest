# Hackfest Platform

A small "Capture-the-Patch" style exploit-and-patch platform for a 1-day event.
Teams register, get challenges (vulnerable code + a briefing), submit fixed
files, and a judge worker grades each submission in an isolated container
against a hidden test suite. A live leaderboard updates as teams solve.

## Quick start

```bash
cp .env.example .env            # edit with real secrets (Neon DATABASE_URL etc.)
python scripts/apply_schema.py  # create tables in Neon (once, idempotent)
docker build -t hackfest/webhook-replay:latest ./challenges/webhook-replay
docker compose up --build
```

API comes up at `http://localhost/api`, leaderboard UI at `http://localhost/`,
and the participant code-editor workspace at `http://localhost/workspace.html`.

## Deploying to Render

... omitted ...

### Team and per-user accounts

This event is designed for admin-invited participants:

- Admins add valid participants by email via the event roster.
- Participants sign in with the shared event ID, their invited email, and a password.
- Teaming remains optional; a single participant can be treated as their own "team" for the leaderboard if needed.
- `POST /api/users/login` accepts the invited email and password, and can also accept a username if you still have legacy accounts.

A user token carries the same `team_id`/`event_id` claims as the team token,
so `POST /api/submissions` and the submission-status route accept either —
rate limits stay **per team** either way, so one eager member can't burn the
team's cooldown faster than the team itself could.

### Participant workspace (side-by-side editor)

`http://localhost/workspace.html` (or `/workspace.html` on Render) is the
participant-facing web UI:

- **Log in** with your event ID, invited email, and password. The page sets a
  strict `Content-Security-Policy` meta so a stray script can't speak to other
  origins.
- **No self-registration** is required for this event flow; organizers control
  who is allowed to participate via the roster.

... omitted ...
