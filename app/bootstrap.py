from __future__ import annotations

from app.db import SessionLocal, init_db
from app.db.migrations import run_content_migrations
from app.db.seed import seed_defaults
from app.services import schedule as schedule_service
from app.services import site_data


async def prepare_database() -> None:
    """Готовит БД к работе и ботам, и веб-панели сайта."""
    await init_db()
    async with SessionLocal() as session:
        await seed_defaults(session)
        await run_content_migrations(session)
        await site_data.ensure_settings(session)
    async with SessionLocal() as session:
        await schedule_service.ensure_horizon(session)
