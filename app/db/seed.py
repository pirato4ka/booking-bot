from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, PriceMode, Service, WeekdayTemplate
from app.utils.slugs import slugify


def service(
    title: str,
    price: int | None,
    duration: int,
    *,
    mode: PriceMode = PriceMode.FIXED,
    note: str | None = None,
    buffer: int = 15,
    description: str = "",
    featured: int | None = None,
) -> dict:
    return {
        "title": title,
        "price": price,
        "duration": duration,
        "mode": mode,
        "note": note,
        "buffer": buffer,
        "description": description,
        "featured": featured,
    }


# Стартовые тексты блоков сайта: слаг, короткое имя для фильтра и подпись.
CATEGORY_DEFAULTS: dict[str, dict[str, str]] = {
    "Холодная плазма": {
        "slug": "plasma",
        "short_title": "Холодная плазма",
        "description": "Рубцы, растяжки, тургор, пигментация и деликатные зоны.",
    },
    "Массаж лица": {
        "slug": "face-massage",
        "short_title": "Массаж лица",
        "description": "Кобидо, буккальный, лимфодренажный и другие техники.",
    },
    "Уход за лицом": {
        "slug": "face-care",
        "short_title": "Уход за лицом",
        "description": "Чистки, маски и уходовые ритуалы под запрос кожи.",
    },
    "Аппаратные процедуры": {
        "slug": "hardware",
        "short_title": "Аппаратные",
        "description": "Кавитация, РФ-лифтинг, вакуум и прессотерапия.",
    },
    "Эпиляция и шугаринг": {
        "slug": "epilation",
        "short_title": "Эпиляция",
        "description": "Шугаринг и электроэпиляция с вниманием к коже.",
    },
    "Курсы коррекции фигуры": {
        "slug": "courses",
        "short_title": "Курсы",
        "description": "Программы для системной работы с телом.",
    },
}

# Порядок карточек в блоке «Популярное» на сайте.
FEATURED_RANKS: dict[str, int] = {
    "Омоложение лица полностью": 1,
    "Массаж лица «Букальный»": 2,
    "Живот: растяжки / подтяжка / жиросжигание": 3,
    "Комбинированная чистка лица": 4,
    "Кавитация": 5,
    "Процедура выходного дня «Релакс»": 6,
}



PLASMA = (
    "Зона обрабатывается аппаратом холодной плазмы. "
    "Точный протокол и количество проходов подбирает мастер."
)

CATALOG: list[tuple[str, str, list[dict]]] = [
    (
        "⚡",
        "Холодная плазма",
        [
            service(
                "Шлифовка шрамов и рубцов",
                None,
                30,
                mode=PriceMode.CUSTOM,
                note="2 500 ₽ до 3 см², далее +300 ₽ за каждый см²",
                description=(
                    "Шлифовка рубцов и шрамов. Стоимость зависит от площади: "
                    "2 500 ₽ до 3 см², каждый следующий см² — 300 ₽."
                ),
            ),
            service("Живот: растяжки / подтяжка / жиросжигание", 10000, 60, buffer=20, description=PLASMA, featured=3),
            service("Бока: растяжки / подтяжка / жиросжигание", 8000, 45, description=PLASMA),
            service("Бока + живот", 15000, 90, buffer=20, description=PLASMA),
            service("Грудь: растяжки / подтяжка", 10000, 45, mode=PriceMode.FROM, description="Стоимость зависит от объёма работы."),
            service("Бёдра: растяжки / подтяжка", 12000, 60, mode=PriceMode.FROM, description="Стоимость зависит от объёма работы."),
            service("Спина полностью", 15000, 90, buffer=20, description=PLASMA),
            service("Верх спины", 8000, 45, description=PLASMA),
            service("Низ спины", 8000, 45, description=PLASMA),
            service("Ягодицы: упругость, омоложение, жиросжигание", 15000, 60, description=PLASMA),
            service("Галифе: омоложение, тургор, жиросжигание", 16000, 60, description=PLASMA),
            service("Подбородок, брыли: подтяжка, жиросжигание", 3000, 30, description=PLASMA),
            service("Интимная подтяжка и отбеливание (жен.)", 10000, 45, buffer=20, description="Лобок и большие половые губы: улучшение тургора, омоложение кожи."),
            service("Интимная подтяжка и отбеливание (муж.)", 10000, 45, buffer=20, description="Ствол и мошонка: улучшение тургора, омоложение кожи."),
            service("Отбеливание паховой области", 10000, 45, description=PLASMA),
            service("Отбеливание межъягодичной складки", 8000, 30, description=PLASMA),
            service("Лечение акне, постакне: щёки", 5000, 40, description=PLASMA),
            service("Лечение акне, постакне: подбородок", 3000, 30, description=PLASMA),
            service("Верхние веки", 5000, 30, buffer=10, description=PLASMA),
            service("Нижние веки", 4000, 30, buffer=10, description=PLASMA),
            service("Глаза полностью", 8000, 45, buffer=10, description=PLASMA),
            service("Гусиные лапки", 5000, 30, buffer=10, description=PLASMA),
            service("Нос", 1500, 20, buffer=10, description=PLASMA),
            service("Морщины вокруг рта", 2500, 20, buffer=10, description=PLASMA),
            service("Околоушные морщины", 3000, 20, buffer=10, description=PLASMA),
            service("Линейные морщины на лбу", 3000, 20, buffer=10, description=PLASMA),
            service("Межбровье", 2500, 20, buffer=10, description=PLASMA),
            service("Зона лба полностью", 5000, 30, buffer=10, description=PLASMA),
            service("Носогубные морщины", 2500, 20, buffer=10, description=PLASMA),
            service("Лицо без зоны вокруг глаз", 8000, 60, description=PLASMA),
            service("Омоложение лица полностью", 10000, 60, description=PLASMA, featured=1),
            service("Шлифовка лица и шеи", 15000, 90, buffer=20, description=PLASMA),
            service("Шея", 5000, 30, buffer=10, description=PLASMA),
            service("Декольте", 6000, 45, buffer=10, description=PLASMA),
            service("Омоложение кистей рук", 5000, 30, buffer=10, description=PLASMA),
            service("Пигментные пятна", 1000, 30, mode=PriceMode.FROM, buffer=10, description="Стоимость зависит от площади и количества зон."),
            service("Алопеция", 2000, 40, mode=PriceMode.FROM, buffer=10, description="Стоимость зависит от объёма работы."),
            service("Вся голова: алопеция", 6000, 60, buffer=10, description=PLASMA),
            service("Загущение волос (вся голова)", 6000, 60, buffer=10, description=PLASMA),
            service(
                "Обезболивание 1 зоны",
                1000,
                15,
                mode=PriceMode.FROM,
                buffer=5,
                description=(
                    "Коленные, локтевые, запястные, голеностопные, тазобедренные суставы. "
                    "Анестезирующее средство на месте — 1 000 ₽."
                ),
            ),
        ],
    ),
    (
        "💆",
        "Массаж лица",
        [
            service("Массаж лица «Кобидо»", 2500, 45, buffer=10),
            service("Массаж лица «Букальный»", 3000, 45, buffer=10, featured=2),
            service("Массаж лица «Классический»", 2500, 40, buffer=10),
            service("Массаж лица «Лимфодренажный»", 2500, 40, buffer=10),
            service("Массаж лица «Щипковый»", 2500, 40, buffer=10),
            service("Массаж головы", 1500, 30, buffer=10),
        ],
    ),
    (
        "🧖",
        "Уход за лицом",
        [
            service("Комбинированная чистка лица", 3500, 60, mode=PriceMode.FROM, buffer=20, featured=4),
            service("Маска для лица «Альгинатная»", 1500, 30, buffer=10),
            service("Маска для лица «Водорослевая»", 1500, 40, buffer=10),
            service("Маска для лица «Пузырьковая»", 2000, 40, buffer=10),
            service("Процедура выходного дня «Релакс»", 4500, 90, buffer=20, description="Массаж лица + гипсовое моделирование.", featured=6),
        ],
    ),
    (
        "✨",
        "Аппаратные процедуры",
        [
            service("Кавитация", 1500, 45, mode=PriceMode.FROM, featured=5),
            service("РФ-лифтинг", 2000, 45, mode=PriceMode.FROM),
            service("Вакуумный массаж", 1500, 40, mode=PriceMode.FROM),
            service("Вибромассаж", 1200, 30, mode=PriceMode.FROM, buffer=10),
            service("Лимфодренажный аппаратный массаж (прессотерапия)", 1500, 45, mode=PriceMode.FROM),
        ],
    ),
    (
        "🌿",
        "Эпиляция и шугаринг",
        [
            service("Шугаринг", 500, 30, mode=PriceMode.FROM, buffer=10),
            service("Электроэпиляция", 1000, 30, mode=PriceMode.FROM, buffer=10),
        ],
    ),
    (
        "🦋",
        "Курсы коррекции фигуры",
        [
            service(
                "Курс «Из гусёнки в бабочку»",
                None,
                60,
                mode=PriceMode.CUSTOM,
                note="Стоимость курса уточняйте у администратора",
                description="Кавитация / лазерный липолиз + прессотерапия. Одна процедура в рамках курса.",
            ),
            service(
                "Курс «Жиротоп»",
                None,
                60,
                mode=PriceMode.CUSTOM,
                note="Стоимость курса уточняйте у администратора",
                description="Кавитация / лазерный липолиз + вибромассаж. Одна процедура в рамках курса.",
            ),
        ],
    ),
]


DEFAULT_TEMPLATE: dict[int, list[dict]] = {
    0: [{"start": 600, "end": 1200}],
    1: [{"start": 600, "end": 1200}],
    2: [{"start": 600, "end": 1200}],
    3: [{"start": 600, "end": 1200}],
    4: [{"start": 600, "end": 1200}],
    5: [{"start": 600, "end": 1080}],
    6: [],
}


async def seed_defaults(session: AsyncSession) -> None:
    """Заполняет каталог и шаблон недели при первом запуске."""
    categories_count = await session.scalar(select(func.count(Category.id)))
    if not categories_count:
        for cat_order, (emoji, title, services) in enumerate(CATALOG):
            defaults = CATEGORY_DEFAULTS.get(title, {})
            category = Category(
                title=title,
                slug=defaults.get("slug") or slugify(title),
                short_title=defaults.get("short_title") or title[:40],
                description=defaults.get("description", ""),
                emoji=emoji,
                sort_order=cat_order,
            )
            session.add(category)
            await session.flush()
            for svc_order, data in enumerate(services):
                session.add(
                    Service(
                        category_id=category.id,
                        title=data["title"],
                        description=data["description"],
                        price_mode=data["mode"],
                        price=data["price"],
                        price_note=data["note"],
                        duration_minutes=data["duration"],
                        buffer_minutes=data["buffer"],
                        featured_rank=data["featured"],
                        sort_order=svc_order,
                    )
                )

    templates_count = await session.scalar(select(func.count(WeekdayTemplate.id)))
    if not templates_count:
        for weekday in range(7):
            windows = DEFAULT_TEMPLATE[weekday]
            session.add(
                WeekdayTemplate(
                    weekday=weekday,
                    is_working=bool(windows),
                    windows=windows,
                )
            )

    await session.commit()

