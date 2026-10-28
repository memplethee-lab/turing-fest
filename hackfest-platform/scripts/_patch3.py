import io

path = "scripts/apply_schema.py"
s = io.open(path, encoding="utf-8").read()

old_doc = (
    "For LOCAL setup only (idempotent, so it's safe to re-run). In production\n"
    "(Render + Neon) this is not needed: the api applies the schema itself at\n"
    "startup via api/app/bootstrap.py \u2014 Render free-tier services don't support\n"
    "preDeployCommand. To change the schema later, either ALTER manually or bump\n"
    "the check below / use a proper migration tool."
)
new_doc = (
    "For LOCAL setup only. schema.sql is fully idempotent (IF NOT EXISTS\n"
    "throughout), so this is safe to re-run and picks up newly added tables.\n"
    "In production the api bootstraps the schema itself at startup\n"
    "(see api/app/bootstrap.py)."
)
assert old_doc in s, "doc"
s = s.replace(old_doc, new_doc, 1)

old_main = (
    "        already = await conn.fetchval(\n"
    "            \"SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='events')\"\n"
    "        )\n"
    "        if already:\n"
    "            print(\"schema already applied, nothing to do\")\n"
    "            return\n"
)
assert old_main in s, "main"
s = s.replace(old_main, "", 1)
s = s.replace('print("schema applied")', 'print("schema applied (idempotent)")', 1)

io.open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched", path)
