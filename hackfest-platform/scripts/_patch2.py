import io

path = "scripts/apply_schema.py"
s = io.open(path, encoding="utf-8").read()

old_doc = '''Runs as the api service's Render preDeployCommand. Idempotent: Render
Postgres (unlike the compose postgres image) has no initdb hook, so this
runs on every deploy but only applies the schema when the tables don't
exist yet. To change the schema later, either ALTER manually or bump the
check below / use a proper migration tool.'''
new_doc = '''Runs as the api service's Render preDeployCommand and is safe to re-run:
schema.sql uses CREATE ... IF NOT EXISTS throughout, so every deploy picks
up any newly added tables without a migration tool.'''
assert old_doc in s
s = s.replace(old_doc, new_doc, 1)

old_main = '''    try:
        already = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='events')"
        )
        if already:
            print("schema already applied, nothing to do")
            return
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            await conn.execute(f.read())
        print("schema applied")'''
new_main = '''    try:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            await conn.execute(f.read())
        print("schema applied (idempotent)")'''
assert old_main in s
s = s.replace(old_main, new_main, 1)

io.open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched", path)
