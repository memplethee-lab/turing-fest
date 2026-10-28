"""
Idempotent schema bootstrap, run by the api at startup.

Replaces the old Render preDeployCommand (which free-tier services don't
support): Neon has no initdb script hook like the compose postgres image, so
the api applies db/schema.sql itself on every startup. The schema uses
CREATE ... IF NOT EXISTS throughout, so re-running is cheap and — crucially —
newly added tables (e.g. admins, users) get created on the next deploy even
when the older tables already exist.
"""
import asyncio
import os

import asyncpg

# Neon poolers can briefly refuse new connections right after a cold start,
# so retry a few times before failing the deploy.
_RETRIES = 10
_RETRY_DELAY_SECONDS = 3


def _read_schema() -> str:
    # Resolve db/schema.sql both from the repo checkout (api/app/../../db/)
    # and from the Render image (db/ copied next to app/ in Dockerfile.render).
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (
        os.path.join(here, "..", "db", "schema.sql"),
        os.path.join(here, "..", "..", "db", "schema.sql"),
    ):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError("db/schema.sql not found next to the api app")


async def _apply(db_url: str) -> None:
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(_read_schema())
        print("schema applied (idempotent)")
    finally:
        await conn.close()


async def bootstrap() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set; skipping schema bootstrap")
        return
    last: Exception | None = None
    for _ in range(_RETRIES):
        try:
            await _apply(db_url)
            return
        except Exception as exc:  # noqa: BLE001 - bubble up after retries
            last = exc
            await asyncio.sleep(_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"schema bootstrap failed after {_RETRIES} attempts: {last}")
