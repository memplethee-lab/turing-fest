"""Second half of the roster/email participant patch (SearchReplace is
rejecting an unchanged file). Delete after running."""
import pathlib

path = pathlib.Path("frontend/workspace.html")
text = path.read_bytes().decode("utf-8")

pairs = [
    (
        '<a href="/" target="_blank">Leaderboard ↗</a>',
        '<a id="leaderboard-link" href="/" target="_blank">Leaderboard ↗</a>',
    ),
    (
        "let openFile = null;\nlet submitWatch = null;",
        "let openFile = null;\nlet submitWatch = null;\nlet myEventId = null;      // so the leaderboard link points at the right event",
    ),
    (
        'async function loadWorkspace() {\n  const list = await api("/challenges");',
        'async function loadWorkspace() {\n  await loadIdentity();\n  const list = await api("/challenges");',
    ),
    (
        "function updateTimer() {",
        "// Best-effort: who am I (display name) and which event, so the leaderboard\n"
        "// link deep-links instead of showing an empty board. A legacy team token has\n"
        "// no user row; that is not worth logging anyone out over.\n"
        "async function loadIdentity() {\n"
        "  try {\n"
        "    const r = await fetch(`${API}/users/me`, { headers: headers() });\n"
        "    if (!r.ok) return;\n"
        "    const u = await r.json();\n"
        "    myEventId = u.event_id || myEventId;\n"
        "    const self = (u.members || []).find(m => m.username === u.username);\n"
        '    me = { kind: "user", name: (self && self.display_name) || u.username, team_id: u.team_id };\n'
        '    const link = document.getElementById("leaderboard-link");\n'
        "    if (myEventId) link.href = `/?event_id=${encodeURIComponent(myEventId)}`;\n"
        "  } catch { /* identity is cosmetic */ }\n"
        "}\n"
        "\n"
        "function updateTimer() {",
    ),
]

for old, new in pairs:
    assert text.count(old) == 1, f"expected one match for {old[:50]!r}, got {text.count(old)}"
    text = text.replace(old, new)

path.write_bytes(text.encode("utf-8"))
print("patched frontend/workspace.html")
