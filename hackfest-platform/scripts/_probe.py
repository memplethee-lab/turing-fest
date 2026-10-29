import pathlib

s = pathlib.Path("frontend/workspace.html").read_text(encoding="utf-8")
tests = [
    '<a href="/" target="_blank">Leaderboard',
    "let openFile = null;\nlet submitWatch = null;",
    'async function loadWorkspace() {\n  const list = await api("/challenges");',
    "function updateTimer() {",
]
for t in tests:
    print(s.count(t), repr(t[:40]))
print("crlf:", s.count("\r\n"))
