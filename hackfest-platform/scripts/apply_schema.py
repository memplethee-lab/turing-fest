"""
Apply db/schema.sql to the Postgres instance at DATABASE_URL.

For LOCAL setup only. schema.sql is fully idempotent (IF NOT EXISTS
throughout), so this is safe to re-run and picks up newly added tables.
In production the api bootstraps the schema itself at startup
(see api/app/bootstrap.py).
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
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            await conn.execute(f.read())
        print("schema applied (idempotent)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
