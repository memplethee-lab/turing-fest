"""README updates for the email-first participant flow. Delete after running."""
import pathlib

path = pathlib.Path("README.md")
text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")

pairs = [
    (
        "Teams then register with that `event_id` via `POST /api/teams/register`.\n"
        "\n"
        "### Team and per-user accounts\n"
        "\n"
        "Teams keep the shared name+password login (`POST /api/teams/register`,\n"
        "`/api/teams/login`) — handy for scripting and as the secret members share.\n"
        "On top of that, each person can get an individual account attached to their\n"
        "team:\n"
        "\n"
        "- `POST /api/users/register` — `{event_id, team_name, team_password, username,\n"
        "  password}`. The team's shared password proves membership; the username is\n"
        "  globally unique.\n"
        "- `POST /api/users/login` — `{username, password}` → user token.\n"
        "- `GET /api/users/me` — who I am, my team, and my teammates.",

        "Teams then register with that `event_id` via `POST /api/teams/register`.\n"
        "\n"
        "### Participant accounts (email-first)\n"
        "\n"
        "Participants are invited by email — the admin pastes the emails into the\n"
        "roster (see \"Closed registration\" below). A participant then opens\n"
        "`/workspace.html` and uses that same email plus a password of their choosing:\n"
        "\n"
        "- `POST /api/users/signup` — `{email, password, display_name?}`. Creates the\n"
        "  account, claims their roster entry, and gives them a **personal team** named\n"
        "  after their display name (default: the email's first half). Signup resolves\n"
        "  the event from the roster, so nobody has to paste an event id.\n"
        "- `POST /api/users/login` — `{login: <email>, password}` → user token. Legacy\n"
        "  `{username, password}` still works. Answers 404 when no account exists yet\n"
        "  and 401 on a wrong password, so the UI can tell \"create your account\" from\n"
        "  \"wrong password\".\n"
        "- `GET /api/users/me` — who I am, my team, and my teammates.\n"
        "\n"
        "Because every participant gets a personal team, the leaderboard (which is\n"
        "scored per team) lists one row per participant by default. Group play is\n"
        "optional and unchanged: `POST /api/teams/register` creates a shared team, and\n"
        "`POST /api/users/register` (`{event_id, team_name, team_password, username,\n"
        "password}`) joins one — members of a shared team score and rank together, and\n"
        "the leaderboard marks those rows \"team of N\".",
    ),
    (
        "- **Log in** as a team (shared name + password) or a personal account. The\n"
        "  token lives in `localStorage`; the page sets a strict\n"
        "  `Content-Security-Policy` meta so a stray script can't speak to other origins.",

        "- **Sign in with the email the organizer registered.** The page resolves the\n"
        "  current event from `GET /api/events/current` (no event id to paste) and posts\n"
        "  to `/api/users/signup` on first visit or `/api/users/login` afterwards. The\n"
        "  token lives in `localStorage`; the page sets a strict\n"
        "  `Content-Security-Policy` meta so a stray script can't speak to other origins.",
    ),
    (
        "3. From then on **both** registration paths demand a roster email:\n"
        "   - `POST /api/teams/register` — `{..., email}` claims one unused invite\n"
        "     atomically (two parties racing for the same email get a single winner;\n"
        "     the loser gets a 403).\n"
        "   - `POST /api/users/register` — `{..., email}` must be **unused or already\n"
        "     claimed by that same team** (so a captain can register their own personal\n"
        "     account with the email they used to create the team), and no two users\n"
        "     in an event can bind the same email.",

        "3. From then on **every** registration path demands a roster email:\n"
        "   - `POST /api/users/signup` — the normal path: the email must be on the\n"
        "     roster. Signup claims it atomically and creates a personal team, so\n"
        "     there is nothing else for the participant to look up.\n"
        "   - `POST /api/teams/register` — `{..., email}` claims one unused invite\n"
        "     atomically (two parties racing for the same email get a single winner;\n"
        "     the loser gets a 403).\n"
        "   - `POST /api/users/register` — `{..., email}` must be **unused or already\n"
        "     claimed by that same team** (so a captain can register their own personal\n"
        "     account with the email they used to create the team), and no two users\n"
        "     in an event can bind the same email.",
    ),
    (
        "  — see \"Closed registration\" above. Both team and personal registration\n"
        "  then require an unclaimed roster email; existing accounts stay valid.",

        "  — see \"Closed registration\" above. Personal signup and team registration\n"
        "  then both require an unclaimed roster email; existing accounts stay valid.",
    ),
]

for old, new in pairs:
    assert text.count(old) == 1, f"expected one match for {old[:60]!r}, got {text.count(old)}"
    text = text.replace(old, new)

path.write_bytes(text.encode("utf-8"))
print("patched README.md")
