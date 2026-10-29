import io

path = "api/app/routes/admin.py"
s = io.open(path, encoding="utf-8").read()

old = "from datetime import datetime, timezone\n\nfrom fastapi import APIRouter, HTTPException, Depends"
new = "from datetime import datetime, timezone\n\nimport asyncpg\nfrom fastapi import APIRouter, HTTPException, Depends"

if "import asyncpg" in s:
    print("already patched")
else:
    assert old in s, "imports block not found"
    s = s.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)
