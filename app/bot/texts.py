from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.db.models import Booking, Category, Service
from app.utils.text import (
    booking_price_label,
    booking_status_label,
    esc,
    item_price_label,
    price_label,
    truncate,
)
from app.utils.timeutil import (
    fmt_date_long,
    fmt_duration,
    fmt_interval,
    fmt_time,
)


def main_menu_text(is_admin: bool = False) -> str:
    lines = [
        f"<b>{esc(settings.studio_name)}</b>",
        f"<i>{esc(settings.studio_tagline)}</i>",
        "",
        "Здесь можно посмотреть услуги, выбрать удобное время и записаться за пару минут.",
    ]
    if settings.studio_contacts:
        lines.extend(["", settings.studio_contacts])
    if is_admin:
        lines.extend(["", "Вы вошли как администратор — доступна панель управления."])
    return "\n".join(lines)


def about_text() -> str:
    lines = [
        f"<b>{esc(settings.studio_name)}</b>",
        f"<i>{esc(settings.studio_tagline)}</i>",
        "",
        "Мы заботимся о красоте и здоровье тела: подбираем уход и программу под ваш запрос.",
        "",
        "<b>Как записаться</b>",
        "1. Выберите услугу в прайсе или нажмите «Записаться».",
        "2. Выберите дату и время из свободных окон.",
        "3. Оставьте телефон — мы свяжемся для подтверждения.",
        "",
        f"⏱ Запись удерживается {settings.hold_minutes} минут до подтверждения.",
        f"❌ Отменить или перенести можно не позднее чем за {settings.cancel_cutoff_hours} ч.",
    ]
    if settings.studio_contacts:
        lines.extend(["", "<b>Контакты</b>", settings.studio_contacts])
    return "\n".join(lines)


def catalog_text(category: Category | None = None, mode: str = "view") -> str:
    if category is None:
        title = "Что добавить в запись?" if mode == "add" else "Выберите раздел"
        return f"<b>{title}</b>\n\nУслуги и цены студии."
    return (
        f"<b>{category.emoji} {esc(category.title)}</b>\n\n"
        "Нажмите на услугу, чтобы посмотреть описание и стоимость."
    )


def service_text(service: Service, mode: str = "view") -> str:
    lines = [f"<b>{esc(service.title)}</b>", ""]
    if service.description:
        lines.extend([esc(service.description), ""])
    lines.append(f"💰 <b>Стоимость:</b> {price_label(service)}")
    lines.append(f"⏱ <b>Длительность:</b> {fmt_duration(service.duration_minutes)}")
    if service.buffer_minutes:
        lines.append(f"🧼 <b>Перерыв после:</b> {fmt_duration(service.buffer_minutes)}")
    if mode == "add":
        lines.extend(["", "Услуга добавится к текущей записи."])
    else:
        lines.extend(["", "Выберите «Записаться», чтобы перейти к выбору времени."])
    return "\n".join(lines)


def _items_lines(booking: Booking) -> list[str]:
    lines = []
    for item in sorted(booking.items, key=lambda value: value.sort_order):
        lines.append(
            f"• {esc(item.title)} — {item_price_label(item)} · "
            f"{fmt_duration(item.duration_minutes)}"
        )
    return lines


def _when_line(booking: Booking) -> str:
    return (
        f"<b>Когда:</b> {fmt_date_long(booking.start_at.date())}, "
        f"{fmt_interval(booking.start_at, booking.end_at)}"
    )


def draft_text(booking: Booking, now: datetime) -> str:
    lines = [
        f"<b>⏳ Черновик записи №{booking.id}</b>",
        "",
        _when_line(booking),
        "<b>Услуги:</b>",
        *_items_lines(booking),
        "",
        f"<b>Итого:</b> {booking_price_label(booking)} · {fmt_duration(booking.total_minutes)}",
    ]
    if booking.hold_expires_at:
        minutes_left = max(0, int((booking.hold_expires_at - now).total_seconds() // 60))
        lines.append(
            f"🕒 Время удерживается до {fmt_time(booking.hold_expires_at)} "
            f"(осталось {minutes_left} мин)."
        )
    lines.extend(["", "Проверьте состав и подтвердите запись."])
    return "\n".join(lines)


def draft_contact_text(
    booking: Booking, name: str, phone: str, comment: str
) -> str:
    lines = [
        f"<b>Проверьте запись №{booking.id}</b>",
        "",
        f"<b>Имя:</b> {esc(name)}",
        f"<b>Телефон:</b> {esc(phone)}",
        _when_line(booking),
        "<b>Услуги:</b>",
        *_items_lines(booking),
        "",
        f"<b>Итого:</b> {booking_price_label(booking)} · {fmt_duration(booking.total_minutes)}",
    ]
    if comment:
        lines.append(f"<b>Комментарий:</b> {esc(comment)}")
    lines.extend(["", "Нажмите «Всё верно, записать» — и мы подтвердим запись."])
    return "\n".join(lines)


def booking_card_text(booking: Booking, *, admin: bool = False) -> str:
    lines = [
        f"<b>Запись №{booking.id}</b> · {booking_status_label(booking.status)}",
        "",
        _when_line(booking),
        "<b>Услуги:</b>",
        *_items_lines(booking),
        "",
        f"<b>Итого:</b> {booking_price_label(booking)} · {fmt_duration(booking.total_minutes)}",
    ]
    if admin:
        lines.append(f"<b>Клиент:</b> {esc(booking.client_name or '—')}")
        lines.append(f"<b>Телефон:</b> {esc(booking.client_phone or '—')}")
        if booking.client and booking.client.username:
            lines.append(f"<b>Telegram:</b> @{esc(booking.client.username)}")
        lines.append(f"<b>Источник:</b> {esc(booking.source)}")
    if booking.comment:
        lines.append(f"<b>Комментарий:</b> {esc(truncate(booking.comment, 300))}")
    if booking.status.value == "cancelled" and booking.cancel_reason:
        lines.append(f"<b>Причина отмены:</b> {esc(booking.cancel_reason)}")
    if booking.client_confirmed:
        lines.append("✅ Клиент подтвердил визит")
    if settings.studio_address:
        lines.extend(["", f"📍 {esc(settings.studio_address)}"])
    return "\n".join(lines)


def booking_success_text(booking: Booking) -> str:
    lines = [
        "✅ <b>Запись подтверждена!</b>",
        "",
        f"<b>Номер:</b> {booking.id}",
        _when_line(booking),
        "<b>Услуги:</b>",
        *_items_lines(booking),
        "",
        f"<b>Итого:</b> {booking_price_label(booking)} · {fmt_duration(booking.total_minutes)}",
    ]
    if settings.studio_address:
        lines.extend(["", f"📍 {esc(settings.studio_address)}"])
    lines.extend(
        [
            "",
            "Мы напомним о визите. Если планы изменятся, отмените или перенесите "
            "запись в «Мои записи» "
            f"не позднее чем за {settings.cancel_cutoff_hours} ч.",
        ]
    )
    return "\n".join(lines)


def my_bookings_text(bookings: list[Booking]) -> str:
    if not bookings:
        return (
            "<b>Мои записи</b>\n\n"
            "Пока нет записей. Нажмите «Записаться» в главном меню — выберем удобное время."
        )
    active = [
        booking for booking in bookings if booking.status.value in ("draft", "confirmed")
    ]
    lines = ["<b>Мои записи</b>", ""]
    if active:
        lines.append("Нажмите на запись, чтобы открыть детали.")
    else:
        lines.append("Активных записей нет — ниже история визитов.")
    return "\n".join(lines)
