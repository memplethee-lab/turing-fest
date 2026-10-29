import io

path = "README.md"
s = io.open(path, encoding="utf-8").read()

def rep(old, new):
    global s
    assert old in s, "MISS: " + old[:60]
    s = s.replace(old, new, 1)

rep(
    "Visit `http://localhost/admin.html`, log in with `ADMIN_PASSWORD` (set in\n`.env`), and you can:",
    "Visit `http://localhost/admin.html`, log in with an admin account\n(username + password). The first login ever is bootstrapped from\n`ADMIN_PASSWORD` (set in `.env`) as user `admin`; after that, accounts live\nin the DB and are managed on the Admins tab.",
)
rep(
    "  shown to teams. Delete a challenge (existing submissions for it are kept).",
    "  shown to teams. **Edit** any of these mid-event (`PATCH /api/admin/challenges/{id}`\n  \u2014 already-awarded solves keep the points granted at solve time), or delete\n  a challenge (existing submissions for it are kept).",
)
rep(
    "  grading result) gets a **regrade** button that re-queues it.\n\nThe admin token is a single shared secret (`ADMIN_PASSWORD`), not\nper-person accounts \u2014 fine for a small organizing team running one event;\nrotate the password between events.",
    "  grading result) gets a **regrade** button that re-queues it.\n- **Admins** \u2014 add/remove per-admin accounts. Each login issues its own\n  token, so removing a departed organizer's account stops them at their\n  next login. The last remaining account can't be deleted, and you can't\n  delete your own while others exist.",
)
rep(
    "Teams then register with that `event_id` via `POST /api/teams/register`.",
    """Teams then register with that `event_id` via `POST /api/teams/register`.

### Team and per-user accounts

Teams keep the shared name+password login (`POST /api/teams/register`,
`/api/teams/login`) \u2014 handy for scripting and as the secret members share.
On top of that, each person can get an individual account attached to their
team:

- `POST /api/users/register` \u2014 `{event_id, team_name, team_password, username,
  password}`. The team's shared password proves membership; the username is
  globally unique.
- `POST /api/users/login` \u2014 `{username, password}` \u2192 user token.
- `GET /api/users/me` \u2014 who I am, my team, and my teammates.

A user token carries the same `team_id`/`event_id` claims as the team token,
so `POST /api/submissions` and the submission-status route accept either \u2014
rate limits stay **per team** either way, so one eager member can't burn the
team's cooldown faster than the team itself could.""",
)
rep(
    "- Per-user (vs per-team) accounts, and per-admin accounts (currently one\n  shared `ADMIN_PASSWORD`)\n- Editing a challenge's briefing/points after creation (currently:\n  delete + recreate)",
    "- A team-facing web UI (register/login/submit) \u2014 today teams script against\n  the API; `index.html` is leaderboard-only\n- Admin self-service password change (currently: add a new account, remove\n  the old one)",
)

io.open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched", path)
