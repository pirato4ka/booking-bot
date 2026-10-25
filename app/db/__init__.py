from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

if settings.db_url.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.db_url, echo=False, future=True)

if settings.db_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        """SQLite по умолчанию не проверяет внешние ключи."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # Бот и веб-панель пишут в один файл: WAL + ожидание блокировки.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _table_columns(connection, table: str) -> set[str]:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _upgrade_schema(connection) -> None:
    """Доводит схему существующей SQLite-базы до актуальной.

    create_all() не добавляет колонки в уже созданные таблицы, поэтому
    новые поля добавляем вручную. Операция идемпотентна.
    """
    category_columns = _table_columns(connection, "categories")
    if "slug" not in category_columns:
        connection.exec_driver_sql(
            "ALTER TABLE categories ADD COLUMN slug VARCHAR(64) NOT NULL DEFAULT ''"
        )
    if "short_title" not in category_columns:
        connection.exec_driver_sql(
            "ALTER TABLE categories ADD COLUMN short_title VARCHAR(40) NOT NULL DEFAULT ''"
        )
    if "description" not in category_columns:
        connection.exec_driver_sql(
            "ALTER TABLE categories ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )

    service_columns = _table_columns(connection, "services")
    if "featured_rank" not in service_columns:
        connection.exec_driver_sql("ALTER TABLE services ADD COLUMN featured_rank INTEGER")


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if settings.db_url.startswith("sqlite"):
            await connection.run_sync(_upgrade_schema)


async def dispose_db() -> None:
    await engine.dispose()

