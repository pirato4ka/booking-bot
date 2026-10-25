from __future__ import annotations

from datetime import date
from typing import Sequence

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards.client import btn, price_plain
from app.callbacks import (
    ABookCb,
    ACatCb,
    ADayCb,
    AdminCb,
    ASvcCb,
    ATplCb,
    ATimeCb,
    AWinCb,
    NavCb,
)
from app.db.models import (
    Booking,
    BookingStatus,
    Category,
    ScheduleDay,
    ScheduleStatus,
    Service,
)
from app.utils.text import money
from app.utils.timeutil import WEEKDAYS_SHORT, fmt_date_short, fmt_time
from app.utils.timeutil import minutes_to_hhmm

DAY_STATUS_ICON = {
    ScheduleStatus.DRAFT: "📝",
    ScheduleStatus.PUBLISHED: "✅",
    ScheduleStatus.CLOSED: "🚫",
}

BOOKING_STATUS_ICON = {
    BookingStatus.DRAFT: "⏳",
    BookingStatus.CONFIRMED: "✅",
    BookingStatus.COMPLETED: "🏁",
    BookingStatus.CANCELLED: "❌",
    BookingStatus.NO_SHOW: "🚷",
}


def admin_menu() -> InlineKeyboardMarkup:
    rows = [
        [btn("📅 Расписание", AdminCb(section="schedule"))],
        [btn("💼 Услуги и цены", AdminCb(section="services"))],
        [btn("🧾 Записи", AdminCb(section="bookings"))],
        [btn("📊 Статистика", AdminCb(section="stats"))],
        [btn("📖 Шаблон недели", AdminCb(section="templates"))],
        [btn("🏠 Главное меню", NavCb(to="main"))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn("⬅️ Админ-меню", AdminCb(section="menu"))]]
    )


def schedule_list(
    days: Sequence[ScheduleDay],
    page: int,
    counts: dict[date, int],
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = []
    for day in days:
        icon = DAY_STATUS_ICON.get(day.status, "•")
        windows = f"{len(day.windows)} окон" if day.windows else "нет окон"
        count = counts.get(day.date, 0)
        label = f"{fmt_date_short(day.date)} {icon} {windows}"
        if count:
            label += f" · {count}"
        rows.append([btn(label, ADayCb(action="open", date=day.date.isoformat()))])

    nav = []
    if has_prev:
        nav.append(btn("◀️", ADayCb(action="list", page=max(0, page - 1))))
    if has_next:
        nav.append(btn("▶️", ADayCb(action="list", page=page + 1)))
    if nav:
        rows.append(nav)

    rows.append(
        [
            btn("⚡ Опубликовать черновики", ADayCb(action="publish_drafts")),
        ]
    )
    rows.append(
        [
            btn("📆 Скопировать прошлую неделю", ADayCb(action="copy_week")),
        ]
    )
    rows.append([btn("📖 Шаблон недели", ATplCb(action="menu"))])
    rows.append([btn("⬅️ Админ-меню", AdminCb(section="menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_day(day: ScheduleDay) -> InlineKeyboardMarkup:
    iso = day.date.isoformat()
    rows = []
    for idx, window in enumerate(sorted(day.windows, key=lambda item: item.start_minute)):
        rows.append(
            [
                btn(
                    f"◀ {server_time(window.start_minute)}",
                    ATimeCb(date=iso, idx=idx, edge="start", delta=-30),
                ),
                btn(
                    f"{server_time(window.start_minute)} ▶",
                    ATimeCb(date=iso, idx=idx, edge="start", delta=30),
                ),
            ]
        )
        rows.append(
            [
                btn(
                    f"◀ {server_time(window.end_minute)}",
                    ATimeCb(date=iso, idx=idx, edge="end", delta=-30),
                ),
                btn(
                    f"{server_time(window.end_minute)} ▶",
                    ATimeCb(date=iso, idx=idx, edge="end", delta=30),
                ),
            ]
        )
        rows.append(
            [
                btn(
                    f"🗑 Удалить {server_time(window.start_minute)}–{server_time(window.end_minute)}",
                    AWinCb(action="del", date=iso, idx=idx),
                )
            ]
        )

    rows.append([btn("➕ Добавить окно 10:00–20:00", AWinCb(action="add", date=iso))])
    rows.append([btn("✍️ Задать окна текстом", AWinCb(action="input", date=iso))])

    preset_row = [
        btn("10–20", ADayCb(action="preset", date=iso, value="full")),
        btn("10–16", ADayCb(action="preset", date=iso, value="short")),
        btn("14–20", ADayCb(action="preset", date=iso, value="evening")),
        btn("12–21", ADayCb(action="preset", date=iso, value="late")),
    ]
    rows.append(preset_row)

    if day.status == ScheduleStatus.PUBLISHED:
        rows.append([btn("🚫 Сделать выходным", ADayCb(action="close", date=iso))])
    else:
        rows.append([btn("✅ Опубликовать день", ADayCb(action="publish", date=iso))])

    rows.append(
        [
            btn("📆 Копировать прошлую неделю", ADayCb(action="copy_prev", date=iso)),
            btn("📖 Из шаблона", ADayCb(action="apply_template", date=iso)),
        ]
    )
    rows.append([btn("⬅️ К расписанию", ADayCb(action="list"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def server_time(minutes: int) -> str:
    return minutes_to_hhmm(minutes)


def _template_window_bounds(window) -> tuple[int, int]:
    """Поддерживает и JSON-словари, и ORM-окна."""
    if isinstance(window, dict):
        start = window.get("start_minute", window.get("start", 0))
        end = window.get("end_minute", window.get("end", 0))
        return int(start), int(end)
    return int(window.start_minute), int(window.end_minute)


def templates_menu(templates: Sequence) -> InlineKeyboardMarkup:
    rows = []
    for template in templates:
        weekday = WEEKDAYS_SHORT[template.weekday].capitalize()
        if template.is_working and template.windows:
            windows = ", ".join(
                f"{minutes_to_hhmm(start)}–{minutes_to_hhmm(end)}"
                for start, end in sorted(
                    (_template_window_bounds(window) for window in template.windows)
                )
            )
            label = f"{weekday}: {windows}"
        else:
            label = f"{weekday}: выходной"
        rows.append([btn(label, ATplCb(action="day", wd=template.weekday))])
    rows.append([btn("⬅️ Админ-меню", AdminCb(section="menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def template_day(weekday: int) -> InlineKeyboardMarkup:
    rows = [
        [
            btn("10–20", ATplCb(action="set", wd=weekday, value="full")),
            btn("10–16", ATplCb(action="set", wd=weekday, value="short")),
        ],
        [
            btn("14–20", ATplCb(action="set", wd=weekday, value="evening")),
            btn("12–21", ATplCb(action="set", wd=weekday, value="late")),
        ],
        [
            btn(
                "10–14 и 15–20",
                ATplCb(action="set", wd=weekday, value="split"),
            )
        ],
        [btn("✍️ Задать окна текстом", ATplCb(action="custom", wd=weekday))],
        [btn("🚫 Сделать выходным", ATplCb(action="set", wd=weekday, value="off"))],
        [btn("⬅️ К шаблону", ATplCb(action="menu"))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_categories(
    categories: Sequence[Category], counts: dict[int, int]
) -> InlineKeyboardMarkup:
    rows = []
    for category in categories:
        label = f"{category.emoji} {category.title} · {counts.get(category.id, 0)}"
        rows.append(
            [
                btn(label, ASvcCb(action="cat", cid=category.id)),
                btn("✏️", ACatCb(action="rename", cid=category.id)),
                btn("🗑", ACatCb(action="del", cid=category.id)),
            ]
        )
    rows.append([btn("➕ Добавить категорию", ACatCb(action="add"))])
    rows.append([btn("⬅️ Админ-меню", AdminCb(section="menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_delete_confirm(category: Category) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("Да, удалить", ACatCb(action="delete_yes", cid=category.id))],
            [btn("Нет", AdminCb(section="services"))],
        ]
    )


def services_list(
    services: Sequence[Service],
    category_id: int,
    page: int,
    has_next: bool,
    active_count: int,
) -> InlineKeyboardMarkup:
    rows = []
    for service in services:
        mark = "" if service.is_active else " (скрыта)"
        rows.append(
            [
                btn(
                    f"{service.title}{mark} · {price_plain(service)}",
                    ASvcCb(action="card", sid=service.id, cid=category_id, page=page),
                )
            ]
        )
    nav = []
    if page > 0:
        nav.append(btn("◀️", ASvcCb(action="cat", cid=category_id, page=page - 1)))
    if has_next:
        nav.append(btn("▶️", ASvcCb(action="cat", cid=category_id, page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append(
        [
            btn(
                "➕ Добавить услугу",
                ASvcCb(action="add", cid=category_id, page=page),
            )
        ]
    )
    rows.append([btn("⬅️ Категории", AdminCb(section="services"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_card(service: Service, category_id: int, page: int) -> InlineKeyboardMarkup:
    back = ASvcCb(action="cat", cid=category_id, page=page)
    rows = [
        [
            btn("Название", ASvcCb(action="edit_title", sid=service.id, cid=category_id)),
            btn("Цена", ASvcCb(action="edit_price", sid=service.id, cid=category_id)),
        ],
        [
            btn("Длительность", ASvcCb(action="edit_duration", sid=service.id, cid=category_id)),
            btn("Буфер", ASvcCb(action="edit_buffer", sid=service.id, cid=category_id)),
        ],
        [btn("Описание", ASvcCb(action="edit_desc", sid=service.id, cid=category_id))],
        [btn("📂 Сменить категорию", ASvcCb(action="movecat", sid=service.id, cid=category_id))],
    ]
    if service.is_active:
        rows.append([btn("🙈 Скрыть из прайса", ASvcCb(action="toggle", sid=service.id, cid=category_id))])
    else:
        rows.append([btn("👁 Вернуть в прайс", ASvcCb(action="toggle", sid=service.id, cid=category_id))])
    rows.append([btn("🗑 Удалить", ASvcCb(action="del", sid=service.id, cid=category_id))])
    rows.append([btn("⬅️ К услугам", back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_move_category(
    service: Service, categories: Sequence[Category], category_id: int = 0
) -> InlineKeyboardMarkup:
    rows = []
    for category in categories:
        rows.append(
            [
                btn(
                    f"{category.emoji} {category.title}",
                    ASvcCb(action="setcat", sid=service.id, cid=category.id),
                )
            ]
        )
    rows.append(
        [
            btn(
                "⬅️ Назад",
                ASvcCb(action="card", sid=service.id, cid=category_id),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_delete_confirm(service: Service, category_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    "Да, удалить",
                    ASvcCb(action="delete_yes", sid=service.id, cid=category_id),
                )
            ],
            [btn("Нет", ASvcCb(action="card", sid=service.id, cid=category_id))],
        ]
    )


def bookings_dates(days: Sequence[tuple[date, int]]) -> InlineKeyboardMarkup:
    rows = []
    for day, count in days:
        label = f"{fmt_date_short(day)} · {count} записей"
        rows.append([btn(label, ABookCb(action="list", date=day.isoformat()))])
    rows.append([btn("⬅️ Админ-меню", AdminCb(section="menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bookings_list(
    bookings: Sequence[Booking], day: date, prev_day: date, next_day: date
) -> InlineKeyboardMarkup:
    rows = []
    for booking in bookings:
        icon = BOOKING_STATUS_ICON.get(booking.status, "•")
        name = booking.client_name or "Клиент"
        label = f"{icon} {fmt_time(booking.start_at)} · {name}"
        rows.append(
            [btn(label, ABookCb(action="card", booking_id=booking.id))]
        )
    rows.append(
        [
            btn("◀️", ABookCb(action="list", date=prev_day.isoformat())),
            btn("📅 Даты", ABookCb(action="dates")),
            btn("▶️", ABookCb(action="list", date=next_day.isoformat())),
        ]
    )
    rows.append([btn("⬅️ Админ-меню", AdminCb(section="menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_card(booking: Booking) -> InlineKeyboardMarkup:
    rows = []
    day = booking.start_at.date().isoformat()
    if booking.status == BookingStatus.CONFIRMED:
        rows.append(
            [
                btn(
                    "🏁 Завершить",
                    ABookCb(action="complete", booking_id=booking.id),
                ),
                btn(
                    "🚷 Не пришёл",
                    ABookCb(action="no_show", booking_id=booking.id),
                ),
            ]
        )
        rows.append(
            [btn("❌ Отменить запись", ABookCb(action="cancel", booking_id=booking.id))]
        )
    rows.append([btn("⬅️ К записям дня", ABookCb(action="list", date=day))])
    rows.append([btn("⬅️ Админ-меню", AdminCb(section="menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cancel_confirm(booking: Booking) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    "Да, отменить",
                    ABookCb(action="cancel_yes", booking_id=booking.id),
                )
            ],
            [btn("Нет", ABookCb(action="card", booking_id=booking.id))],
        ]
    )


def stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("🔄 Обновить", AdminCb(section="stats"))],
            [btn("📅 Расписание", AdminCb(section="schedule"))],
            [btn("🧾 Записи", AdminCb(section="bookings"))],
            [btn("⬅️ Админ-меню", AdminCb(section="menu"))],
        ]
    )
