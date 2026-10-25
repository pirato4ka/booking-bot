from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Category, PriceMode, Service, SiteSetting

SITE_JSON_RELATIVE = Path("assets") / "data" / "site.json"

# Стартовые значения совпадают с текущим содержимым site/index.html,
# чтобы после подключения панели сайт выглядел точно так же.
DEFAULT_SETTINGS: dict[str, str] = {
    "studio_name": "Адам и Ева",
    "studio_tagline": "студия красоты и тела",
    "city": "Славянск-на-Кубани",
    "phone": "+7 (988) 668-65-24",
    "address": "г. Славянск-на-Кубани, ул. Запорожская, 102",
    "map_url": (
        "https://yandex.ru/maps/?text=%D0%A1%D0%BB%D0%B0%D0%B2%D1%8F%D0%BD%D1%81%D0%BA-"
        "%D0%BD%D0%B0-%D0%9A%D1%83%D0%B1%D0%B0%D0%BD%D0%B8%2C%20%D1%83%D0%BB%D0%B8"
        "%D1%86%D0%B0%20%D0%97%D0%B0%D0%BF%D0%BE%D1%80%D0%BE%D0%B6%D1%81%D0%BA"
        "%D0%B0%D1%8F%2C%20102"
    ),
    "hours_weekdays": "10:00–20:00",
    "hours_saturday": "10:00–18:00",
    "hours_sunday": "выходной",
    "telegram": "",
    "max": "",
    "instagram": "",
    "hero_title": "Красота, которая начинается с *заботы о себе*",
    "hero_lead": (
        "Студия «Адам и Ева» — пространство, где лицо и тело получают внимание без спешки. "
        "Подбираем процедуру под ваш запрос, объясняем этапы и сопровождаем до результата."
    ),
    "about_lead": "«Адам и Ева» — студия красоты и эстетики тела в Славянске-на-Кубани.",
    "about_text_one": (
        "Мы работаем с лицом и телом: холодная плазма, массаж, уходовые ритуалы, аппаратные "
        "методики, эпиляция и программы коррекции фигуры. В основе — не поток процедур, "
        "а внимательный подбор протокола под ваш запрос."
    ),
    "about_text_two": (
        "Можно начать с одной процедуры или собрать программу. Администратор поможет выбрать "
        "формат и подскажет по длительности, а мастер на консультации уточнит детали "
        "и противопоказания."
    ),
}


def phone_raw(display: str) -> str:
    """«+7 (988) 668-65-24» -> «+79886686524» для ссылки tel:."""
    digits = "".join(char for char in (display or "") if char.isdigit())
    return f"+{digits}" if digits else ""


def site_dir_path(site_dir: str | Path | None = None) -> Path:
    return Path(site_dir if site_dir is not None else settings.site_dir).resolve()


def export_path(site_dir: str | Path | None = None) -> Path:
    return site_dir_path(site_dir) / SITE_JSON_RELATIVE


def _mode_value(mode: PriceMode | str) -> str:
    return mode.value if isinstance(mode, PriceMode) else str(mode)


async def get_settings_map(session: AsyncSession) -> dict[str, str]:
    """Значения из БД поверх стартовых: отсутствующие ключи не теряются."""
    values = dict(DEFAULT_SETTINGS)
    rows = await session.scalars(select(SiteSetting))
    for row in rows:
        values[row.key] = row.value
    return values


async def ensure_settings(session: AsyncSession) -> None:
    existing = set(await session.scalars(select(SiteSetting.key)))
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            session.add(SiteSetting(key=key, value=value))
    await session.commit()


async def save_settings(session: AsyncSession, values: dict[str, str]) -> None:
    existing = {row.key: row for row in await session.scalars(select(SiteSetting))}
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        row = existing.get(key)
        if row is None:
            session.add(SiteSetting(key=key, value=value))
        else:
            row.value = value
    await session.commit()


async def build_payload(session: AsyncSession) -> dict[str, Any]:
    """Снимок сайта: только активные категории и услуги в порядке показа."""
    categories = list(
        await session.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order, Category.id)
        )
    )
    services = list(
        await session.scalars(
            select(Service)
            .where(Service.is_active.is_(True))
            .order_by(Service.sort_order, Service.id)
        )
    )

    counts: dict[int, int] = {}
    for service in services:
        counts[service.category_id] = counts.get(service.category_id, 0) + 1

    category_items: list[dict[str, Any]] = []
    for category in categories:
        category_items.append(
            {
                "slug": category.slug,
                "title": category.title,
                "short": category.short_title or category.title,
                "emoji": category.emoji,
                "description": category.description,
                "count": counts.get(category.id, 0),
            }
        )

    category_slugs = {category.id: category.slug for category in categories}
    service_items: list[dict[str, Any]] = []
    for service in services:
        slug = category_slugs.get(service.category_id)
        if not slug:
            continue
        service_items.append(
            {
                "id": service.id,
                "category": slug,
                "title": service.title,
                "price": service.price,
                "mode": _mode_value(service.price_mode),
                "note": service.price_note or "",
                "duration": service.duration_minutes,
                "description": service.description or "",
                "featured": service.featured_rank or 0,
            }
        )

    values = await get_settings_map(session)
    values["phone_raw"] = phone_raw(values.get("phone", ""))

    return {
        "version": 1,
        "generated_at": datetime.now(settings.tz).isoformat(timespec="seconds"),
        "settings": values,
        "categories": category_items,
        "services": service_items,
    }


def dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


async def export_payload(session: AsyncSession, site_dir: str | Path | None = None) -> Path:
    """Атомарно пишет site.json, который читает статический сайт."""
    payload = await build_payload(session)
    path = export_path(site_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(dump_payload(payload), encoding="utf-8")
    os.replace(temporary, path)
    return path


async def payload_json(session: AsyncSession) -> str:
    return dump_payload(await build_payload(session))


def published_at(site_dir: str | Path | None = None) -> datetime | None:
    path = export_path(site_dir)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=settings.tz)

