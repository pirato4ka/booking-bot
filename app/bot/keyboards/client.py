from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.callbacks import (
    CatCb,
    DateCb,
    DraftCb,
    MyCb,
    NavCb,
    PickSvcCb,
    SlotCb,
    SvcCb,
)
from app.db.models import Booking, BookingStatus, PriceMode, Service
from app.services.availability import DayAvailability
from app.utils.text import money
from app.utils.timeutil import fmt_date_short, fmt_time, minutes_to_hhmm

PAGE_SIZE = 8


def btn(text: str, callback: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback.pack())


def price_plain(service: Service) -> str:
    if service.price_mode == PriceMode.FIXED:
        return f"{money(service.price)} ₽"
    if service.price_mode == PriceMode.FROM:
        return f"от {money(service.price)} ₽"
    return (service.price_note or "по прайсу")[:40]


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [btn("🗓 Записаться", NavCb(to="book"))],
        [
            btn("💰 Прайс", NavCb(to="price")),
            btn("📋 Мои записи", NavCb(to="my")),
        ],
        [btn("ℹ️ О студии", NavCb(to="about"))],
    ]
    if is_admin:
        rows.append([btn("⚙️ Админ-панель", NavCb(to="admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn("🏠 Главное меню", NavCb(to="main"))]]
    )


def categories_kb(
    categories: Sequence, counts: dict[int, int], mode: str
) -> InlineKeyboardMarkup:
    rows = []
    for category in categories:
        count = counts.get(category.id, 0)
        label = f"{category.emoji} {category.title}"
        if count:
            label += f" · {count}"
        rows.append([btn(label, CatCb(cid=category.id, mode=mode))])
    rows.append([btn("🏠 Главное меню", NavCb(to="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_kb(
    services: Sequence[Service],
    category_id: int,
    mode: str,
    page: int,
    has_next: bool,
    back_callback: CallbackData,
) -> InlineKeyboardMarkup:
    rows = []
    for service in services:
        rows.append(
            [
                btn(
                    f"{service.title} · {price_plain(service)}",
                    SvcCb(sid=service.id, mode=mode, cid=category_id, page=page),
                )
            ]
        )
    nav = []
    if page > 0:
        nav.append(btn("◀️", CatCb(cid=category_id, mode=mode, page=page - 1)))
    if has_next:
        nav.append(btn("▶️", CatCb(cid=category_id, mode=mode, page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([btn("⬅️ Назад", back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_card_kb(
    service: Service,
    mode: str,
    category_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    labels = {"view": "🗓 Записаться", "book": "✅ Выбрать", "add": "➕ Добавить"}
    pick_mode = "add" if mode == "add" else "book"
    rows = [
        [btn(labels.get(mode, "✅ Выбрать"), PickSvcCb(sid=service.id, mode=pick_mode))],
        [btn("⬅️ К услугам", CatCb(cid=category_id, mode=mode, page=page))],
        [btn("🏠 Главное меню", NavCb(to="main"))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def date_picker_kb(
    days: Sequence[DayAvailability],
    offset: int,
    back_callback: CallbackData,
    *,
    page_size: int = 7,
) -> InlineKeyboardMarkup:
    rows = []
    pair: list[InlineKeyboardButton] = []
    for availability in days:
        pair.append(
            btn(
                f"{fmt_date_short(availability.date)} · {len(availability.slots)}",
                DateCb(date=availability.date.isoformat(), offset=offset),
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    nav = []
    if offset > 0:
        nav.append(
            btn("◀️ Раньше", DateCb(date="", offset=max(0, offset - page_size)))
        )
    if len(days) == page_size:
        nav.append(btn("Позже ▶️", DateCb(date="", offset=offset + page_size)))
    if nav:
        rows.append(nav)
    rows.append([btn("⬅️ Назад", back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slots_kb(
    day: date,
    slots: Iterable[int],
    offset: int,
    back_callback: CallbackData,
) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for start in slots:
        start_at = datetime.combine(day, datetime.min.time()).replace(
            hour=start // 60, minute=start % 60
        )
        row.append(
            btn(
                minutes_to_hhmm(start),
                SlotCb(start=start_at.isoformat(timespec="minutes")),
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("🕒 Другая дата", DateCb(date="", offset=offset))])
    rows.append([btn("⬅️ Назад", back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def comment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("⏭ Пропустить", DraftCb(action="skip_comment"))],
            [btn("🗑 Отменить запись", DraftCb(action="clear"))],
        ]
    )


def draft_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("✅ Подтвердить", DraftCb(action="ask_confirm"))],
            [btn("➕ Добавить услугу", DraftCb(action="add"))],
            [btn("🕒 Изменить время", DraftCb(action="time"))],
            [btn("🗑 Очистить", DraftCb(action="clear"))],
            [btn("🏠 Главное меню", NavCb(to="main"))],
        ]
    )


def draft_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("✅ Всё верно, записать", DraftCb(action="confirm"))],
            [btn("✍️ Изменить телефон", DraftCb(action="edit_phone"))],
            [btn("⬅️ Назад", DraftCb(action="back"))],
        ]
    )


def booking_success_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("📋 Мои записи", MyCb(action="list"))],
            [btn("🏠 Главное меню", NavCb(to="main"))],
        ]
    )


def my_list_kb(bookings: Sequence[Booking]) -> InlineKeyboardMarkup:
    rows = []
    for booking in bookings:
        title = booking.items[0].title if booking.items else "Запись"
        if len(booking.items) > 1:
            title = f"{title} +{len(booking.items) - 1}"
        rows.append(
            [
                btn(
                    f"{booking.start_at.strftime('%d.%m')} {fmt_time(booking.start_at)} · {title}",
                    MyCb(action="card", booking_id=booking.id),
                )
            ]
        )
    rows.append([btn("🏠 Главное меню", NavCb(to="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_card_kb(booking: Booking, now: datetime) -> InlineKeyboardMarkup:
    rows = []
    if booking.status == BookingStatus.CONFIRMED and booking.start_at >= now:
        rows.append([btn("✅ Я приду", MyCb(action="ack", booking_id=booking.id))])
        rows.append(
            [
                btn("🕒 Перенести", MyCb(action="move", booking_id=booking.id)),
                btn("❌ Отменить", MyCb(action="cancel", booking_id=booking.id)),
            ]
        )
    rows.append([btn("⬅️ К записям", MyCb(action="list"))])
    rows.append([btn("🏠 Главное меню", NavCb(to="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirm_kb(booking_id: int, back_action: str = "card") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("Да, отменить", MyCb(action="cancel_yes", booking_id=booking_id))],
            [btn("Нет, оставить", MyCb(action=back_action, booking_id=booking_id))],
        ]
    )
