"""
Apply db/schema.sql to the Postgres instance at DATABASE_URL.

Runs as the api service's Render preDeployCommand. Idempotent: Render
Postgres (unlike the compose postgres image) has no initdb hook, so this
runs on every deploy but only applies the schema when the tables don't
exist yet. To change the schema later, either ALTER manually or bump the
check below / use a proper migration tool.
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
