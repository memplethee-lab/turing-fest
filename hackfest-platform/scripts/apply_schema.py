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


async def main() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
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
