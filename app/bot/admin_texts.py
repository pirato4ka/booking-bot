from __future__ import annotations

from datetime import date

from app.config import settings
from app.db.models import Booking, Category, ScheduleDay, Service
from app.utils.text import (
    esc,
    money,
    plural_bookings,
    price_label,
    schedule_status_label,
)
from app.utils.timeutil import (
    WEEKDAYS_FULL,
    fmt_date_long,
    fmt_duration,
    fmt_time,
    minutes_to_hhmm,
)


def admin_menu_text(stats: dict | None = None) -> str:
    lines = ["<b>⚙️ Панель управления</b>", ""]
    if stats:
        lines.extend(
            [
                f"📅 Сегодня записей: <b>{stats.get('today', 0)}</b>",
                f"📆 На 7 дней: <b>{stats.get('week', 0)}</b> "
                f"{plural_bookings(stats.get('week', 0))}",
                f"⏳ Активных удержаний: <b>{stats.get('holds', 0)}</b>",
                f"📝 Черновиков расписания: <b>{stats.get('unpublished', 0)}</b>",
                "",
            ]
        )
    lines.append("Выберите раздел:")
    return "\n".join(lines)


def schedule_list_text(
    days: list[ScheduleDay], page: int, horizon: int, drafts_total: int
) -> str:
    published = sum(1 for day in days if day.status.value == "published")
    drafts = sum(1 for day in days if day.status.value == "draft")
    closed = sum(1 for day in days if day.status.value == "closed")
    lines = [
        "<b>📅 Расписание</b>",
        "",
        f"Страница {page + 1} · дней: {len(days)} из {horizon}",
        f"✅ опубликовано: {published} · 📝 черновиков: {drafts} · 🚫 выходных: {closed}",
    ]
    if drafts_total:
        lines.append(
            f"\nВсего черновиков впереди: <b>{drafts_total}</b>. "
            "Их можно опубликовать одной кнопкой — пустые дни заполнятся по шаблону."
        )
    lines.extend(
        [
            "",
            "✅ — день виден клиентам, 📝 — черновик, 🚫 — выходной.",
            "Число справа — количество записей.",
        ]
    )
    return "\n".join(lines)


def day_editor_text(day: ScheduleDay, bookings_count: int = 0) -> str:
    lines = [
        f"<b>{fmt_date_long(day.date)}</b>",
        f"Статус: {schedule_status_label(day.status)}",
    ]
    if day.windows:
        windows = ", ".join(
            f"{minutes_to_hhmm(window.start_minute)}–{minutes_to_hhmm(window.end_minute)}"
            for window in sorted(day.windows, key=lambda item: item.start_minute)
        )
        lines.append(f"Окна: <b>{windows}</b>")
    else:
        lines.append("Окна: <b>не заданы</b>")
    if bookings_count:
        lines.append(f"Записей в этот день: <b>{bookings_count}</b>")
    lines.extend(
        [
            "",
            "Границы окон меняются кнопками ◀ ▶ (шаг 30 минут).",
            "Опубликованный день сразу виден клиентам; выходной скрывает день из записи.",
        ]
    )
    return "\n".join(lines)


def template_text(weekday: int, windows: list[tuple[int, int]]) -> str:
    if windows:
        current = ", ".join(
            f"{minutes_to_hhmm(start)}–{minutes_to_hhmm(end)}" for start, end in windows
        )
    else:
        current = "выходной"
    return (
        f"<b>Шаблон: {WEEKDAYS_FULL[weekday]}</b>\n\n"
        f"Сейчас: <b>{current}</b>\n\n"
        "Шаблон применяется к новым дням горизонта и по кнопке «Из шаблона». "
        "Уже опубликованные дни автоматически не меняются."
    )


def service_admin_text(service: Service) -> str:
    lines = [
        f"<b>{esc(service.title)}</b>",
        f"Категория: {esc(service.category.title) if service.category else '—'}",
        f"Цена: {price_label(service)}",
        f"Длительность: {fmt_duration(service.duration_minutes)}",
        f"Буфер после услуги: {fmt_duration(service.buffer_minutes)}",
        f"Статус: {'активна' if service.is_active else 'скрыта из прайса'}",
    ]
    if service.description:
        lines.extend(["", esc(service.description)])
    lines.extend(["", "Выберите поле для изменения."])
    return "\n".join(lines)


def category_admin_text(category: Category, services_count: int) -> str:
    return (
        f"<b>{category.emoji} {esc(category.title)}</b>\n\n"
        f"Услуг: {services_count}\n\n"
        "Нажмите на услугу, чтобы изменить цену, длительность или описание."
    )


def admin_bookings_text(day: date, bookings: list[Booking]) -> str:
    active = [
        booking for booking in bookings if booking.status.value in ("draft", "confirmed")
    ]
    lines = [
        f"<b>🧾 Записи: {fmt_date_long(day)}</b>",
        "",
        f"Всего: {len(bookings)} · активных: {len(active)}",
    ]
    if bookings:
        lines.append("Нажмите на запись, чтобы открыть карточку.")
    else:
        lines.append("На этот день записей нет.")
    return "\n".join(lines)


def booking_removed_text(day: date) -> str:
    return f"Запись отменена. День: {fmt_date_long(day)}."


def stats_text(stats: dict) -> str:
    lines = [
        "<b>📊 Статистика</b>",
        "",
        f"Сегодня записей: <b>{stats.get('today', 0)}</b>",
        f"Завтра записей: <b>{stats.get('tomorrow', 0)}</b>",
        f"На 7 дней: <b>{stats.get('week', 0)}</b>",
        f"Выручка за месяц (завершённые): <b>{money(stats.get('month_revenue', 0))} ₽</b>",
        f"Новых клиентов за месяц: <b>{stats.get('new_clients', 0)}</b>",
        f"Активных удержаний: <b>{stats.get('holds', 0)}</b>",
        f"Черновиков расписания: <b>{stats.get('unpublished', 0)}</b>",
        "",
        f"Горизонт расписания: {stats.get('horizon', settings.schedule_horizon_days)} дней.",
    ]
    return "\n".join(lines)


def next_booking_text(booking: Booking) -> str:
    return f"{fmt_time(booking.start_at)} · {esc(booking.client_name or 'Клиент')}"
