"""Run database migrations against the configured database."""

import asyncio
import logging
from pathlib import Path

import asyncpg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATION_DIR = Path(__file__).resolve().parents[3] / "infra" / "migrations"


async def run_migrations() -> None:
    import os

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://agr:password@localhost:5432/agr_dev"
    )
    # Convert SQLAlchemy URL to asyncpg format
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    migration_files = sorted(MIGRATION_DIR.glob("*.sql"))
    for migration in migration_files:
        logger.info("Running migration: %s", migration.name)
        sql = migration.read_text()
        await conn.execute(sql)
        logger.info("Completed: %s", migration.name)

    await conn.close()
    logger.info("All migrations completed.")


if __name__ == "__main__":
    asyncio.run(run_migrations())
