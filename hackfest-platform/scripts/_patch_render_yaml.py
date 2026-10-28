import io

path = "render.yaml"
s = io.open(path, encoding="utf-8").read()

s = s.replace(
    """# Deploys: FastAPI api + nginx frontend (both Docker runtime, free plan),
# Render Postgres (free dev instance) and Render Key Value / Redis (free).""",
    """# Deploys: FastAPI api + nginx frontend (both Docker runtime, free plan)
# and Render Key Value / Redis (free). Postgres is EXTERNAL: Neon - the
# connection string is entered once in the Render Dashboard (DATABASE_URL
# below is `sync: false`; never hardcode the real one here).""",
)
s = s.replace(
    """# the EXTERNAL Postgres + Key Value URLs""",
    """# the same Neon DATABASE_URL + the Key Value EXTERNAL URL""",
)
s = s.replace(
    """    # Applies db/schema.sql on every deploy (no-op once the schema exists).""",
    """    # Applies db/schema.sql on every deploy (no-op once the schema exists;
    # Neon has no initdb hook, so this is what provisions the tables).""",
)
s = s.replace(
    """      - key: DATABASE_URL
        fromDatabase:
          name: hackfest-postgres
          property: connectionString""",
    """      # Neon connection string - paste it in the Render Dashboard when the
      # Blueprint sync asks. Keep ?sslmode=require (asyncpg requires TLS
      # against Neon).
      - key: DATABASE_URL
        sync: false""",
)
# drop the Render Postgres resource entirely
i = s.find("databases:")
if i != -1:
    s = s[:i].rstrip() + "\n"

io.open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched")
