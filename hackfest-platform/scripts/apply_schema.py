"""
Apply db/schema.sql to the Postgres instance at DATABASE_URL.

For LOCAL setup only (idempotent, so it's safe to re-run). In production
(Render + Neon) this is not needed: the api applies the schema itself at
startup via api/app/bootstrap.py — Render free-tier services don't support
preDeployCommand. To change the schema later, either ALTER manually or bump
the check below / use a proper migration tool.
"""
import asyncio
import os

import asyncpg

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
DOTENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")


def get_database_url() -> str:
    """DATABASE_URL from the environment; falls back to the repo .env file
    so `python scripts/apply_schema.py` works straight after `cp .env.example
    .env`, without exporting anything."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        with open(DOTENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    raise SystemExit("DATABASE_URL is not set and no .env file was found")


async def main() -> None:
    conn = await asyncpg.connect(get_database_url())
    try:
        already = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='events')"
        )
        if already:
            print("schema already applied, nothing to do")
            return
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            await conn.execute(f.read())
        print("schema applied")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
