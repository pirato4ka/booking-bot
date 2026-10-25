from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, PriceMode, Service


async def active_categories(session: AsyncSession) -> list[Category]:
    result = await session.scalars(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_order, Category.id)
    )
    return list(result)


async def all_categories(session: AsyncSession) -> list[Category]:
    result = await session.scalars(select(Category).order_by(Category.sort_order, Category.id))
    return list(result)


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    return await session.get(Category, category_id)


async def category_service_counts(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(
        select(Service.category_id, func.count(Service.id))
        .where(Service.is_active.is_(True))
        .group_by(Service.category_id)
    )
    return {category_id: count for category_id, count in rows}


async def services_by_category(
    session: AsyncSession,
    category_id: int,
    *,
    include_inactive: bool = False,
) -> list[Service]:
    statement = select(Service).where(Service.category_id == category_id)
    if not include_inactive:
        statement = statement.where(Service.is_active.is_(True))
    statement = statement.order_by(Service.sort_order, Service.id)
    return list(await session.scalars(statement))


async def get_service(session: AsyncSession, service_id: int) -> Service | None:
    return await session.get(Service, service_id)


async def active_services_by_ids(
    session: AsyncSession, service_ids: list[int]
) -> list[Service]:
    if not service_ids:
        return []
    result = await session.scalars(
        select(Service).where(Service.id.in_(service_ids), Service.is_active.is_(True))
    )
    by_id = {service.id: service for service in result}
    return [by_id[service_id] for service_id in service_ids if service_id in by_id]


async def create_category(session: AsyncSession, title: str, emoji: str = "✨") -> Category:
    max_order = await session.scalar(select(func.max(Category.sort_order))) or 0
    category = Category(title=title.strip(), emoji=emoji, sort_order=max_order + 1)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


async def create_service(
    session: AsyncSession,
    *,
    category_id: int,
    title: str,
    price_mode: PriceMode,
    price: int | None,
    price_note: str | None,
    duration_minutes: int,
    buffer_minutes: int,
    description: str = "",
) -> Service:
    max_order = (
        await session.scalar(
            select(func.max(Service.sort_order)).where(Service.category_id == category_id)
        )
        or 0
    )
    service = Service(
        category_id=category_id,
        title=title.strip(),
        description=description.strip(),
        price_mode=price_mode,
        price=price,
        price_note=price_note,
        duration_minutes=duration_minutes,
        buffer_minutes=buffer_minutes,
        sort_order=max_order + 1,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service


async def save_service(session: AsyncSession, service: Service) -> None:
    await session.commit()


async def rename_category(session: AsyncSession, category: Category, title: str) -> Category:
    title = title.strip()
    if not title:
        raise ValueError("Название категории не может быть пустым")
    category.title = title[:120]
    await session.commit()
    return category


async def delete_category(session: AsyncSession, category: Category) -> None:
    """Удаляет пустую категорию. Категории с услугами не удаляем."""
    services = await services_by_category(session, category.id, include_inactive=True)
    if services:
        raise ValueError("В категории есть услуги. Сначала перенесите или удалите их.")
    await session.delete(category)
    await session.commit()



async def total_active_services(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count(Service.id)).where(Service.is_active.is_(True))
        )
        or 0
    )
