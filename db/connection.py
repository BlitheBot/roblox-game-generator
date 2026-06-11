import asyncpg
import os
import pathlib
import structlog

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ["DATABASE_URL"]
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        log.info("db.pool_created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log.info("db.pool_closed")


async def run_migrations() -> None:
    pool = await get_pool()
    migrations_dir = pathlib.Path(__file__).parent.parent / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for sql_file in sql_files:
            already_applied = await conn.fetchval(
                "SELECT 1 FROM _migrations WHERE filename = $1", sql_file.name
            )
            if already_applied:
                continue
            sql = sql_file.read_text()
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _migrations (filename) VALUES ($1)", sql_file.name
            )
            log.info("db.migration_applied", file=sql_file.name)
