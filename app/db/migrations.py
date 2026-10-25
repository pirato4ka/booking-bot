from __future__ import annotations

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, PriceMode, Service
from app.db.seed import CATEGORY_DEFAULTS, FEATURED_RANKS
from app.utils.slugs import slugify


async def _fill_category_fields(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            select(
                Category.id,
                Category.title,
                Category.slug,
                Category.short_title,
                Category.description,
            ).order_by(Category.sort_order, Category.id)
        )
    ).all()
    used = {row.slug for row in rows if row.slug}

    for row in rows:
        defaults = CATEGORY_DEFAULTS.get(row.title, {})
        base = row.slug or defaults.get("slug") or slugify(row.title, f"category-{row.id}")
        slug = base
        suffix = 2
        while slug in used and slug != row.slug:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)

        if row.slug != slug:
            await session.execute(
                update(Category).where(Category.id == row.id).values(slug=slug)
            )
        if not row.short_title:
            short_title = defaults.get("short_title") or row.title[:40]
            await session.execute(
                update(Category).where(Category.id == row.id).values(short_title=short_title)
            )
        if not row.description and defaults.get("description"):
            await session.execute(
                update(Category)
                .where(Category.id == row.id)
                .values(description=defaults["description"])
            )


async def _fill_featured_ranks(session: AsyncSession) -> None:
    featured = await session.scalar(
        select(func.count(Service.id)).where(Service.featured_rank.is_not(None))
    )
    if featured:
        return
    for title, rank in FEATURED_RANKS.items():
        await session.execute(
            update(Service).where(Service.title == title).values(featured_rank=rank)
        )


async def run_content_migrations(session: AsyncSession) -> None:
    """Заполняет новые поля контента в уже существующей базе.

    После миграции 60 услуг остаются на месте, а категории получают
    стабильные слаги, короткие подписи и описания для сайта.
    """
    await _fill_category_fields(session)
    await _fill_featured_ranks(session)
    await session.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS ix_categories_slug ON categories (slug)")
    )
    await session.commit()
