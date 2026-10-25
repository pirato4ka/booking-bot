from __future__ import annotations

import html
from typing import Any

from app.db.models import BookingStatus, PriceMode, ScheduleStatus
from app.utils.timeutil import fmt_duration


def esc(value: Any) -> str:
    """Экранирование пользовательского текста для HTML-разметки Telegram."""
    return html.escape(str(value), quote=False)


def money(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", " ")


def price_label(service: Any) -> str:
    mode = service.price_mode
    if mode == PriceMode.FIXED or mode == "fixed":
        return f"{money(service.price)} ₽"
    if mode == PriceMode.FROM or mode == "from":
        return f"от {money(service.price)} ₽"
    note = (service.price_note or "").strip()
    return esc(note) if note else "по прайсу"


def booking_price_label(booking: Any) -> str:
    if getattr(booking, "price_is_estimate", False):
        if booking.total_price:
            return f"от {money(booking.total_price)} ₽"
        return "по прайсу"
    return f"{money(booking.total_price)} ₽"


def item_price_label(item: Any) -> str:
    mode = getattr(item, "price_mode", PriceMode.FIXED)
    if mode == PriceMode.FIXED or mode == "fixed":
        return f"{money(item.price)} ₽"
    if mode == PriceMode.FROM or mode == "from":
        return f"от {money(item.price)} ₽"
    return "по прайсу"


def booking_status_label(status: Any) -> str:
    mapping = {
        BookingStatus.DRAFT: "⏳ черновик",
        BookingStatus.CONFIRMED: "✅ подтверждена",
        BookingStatus.CANCELLED: "❌ отменена",
        BookingStatus.COMPLETED: "🏁 завершена",
        BookingStatus.NO_SHOW: "🚷 не пришёл",
    }
    return mapping.get(status, str(status))


def schedule_status_label(status: Any) -> str:
    mapping = {
        ScheduleStatus.DRAFT: "📝 черновик",
        ScheduleStatus.PUBLISHED: "✅ опубликован",
        ScheduleStatus.CLOSED: "🚫 выходной",
    }
    return mapping.get(status, str(status))


def plural_services(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "услуга"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "услуги"
    return "услуг"


def plural_bookings(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "запись"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "записи"
    return "записей"


def plural_days(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "день"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def items_duration_text(booking: Any) -> str:
    return fmt_duration(booking.total_minutes)


def truncate(value: str, limit: int = 120) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
