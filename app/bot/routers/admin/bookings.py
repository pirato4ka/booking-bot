from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.admin_texts import admin_bookings_text
from app.bot.keyboards.admin import (
    admin_cancel_confirm,
    booking_card,
    bookings_dates,
    bookings_list,
)
from app.bot.texts import booking_card_text
from app.callbacks import ABookCb, AdminCb
from app.db.models import BookingStatus
from app.filters import IsAdmin
from app.services import bookings as bookings_service
from app.services import reports
from app.services.bookings import BookingError
from app.services.notifications import safe_send
from app.utils.timeutil import fmt_date_long, today
from app.utils.ui import edit_or_send

router = Router(name="admin_bookings")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

DATE_RANGE_BACK = 7
DATE_RANGE_FORWARD = 21


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


async def _render_dates(callback: CallbackQuery, session) -> None:
    days: list[tuple[date, int]] = []
    start = today() - timedelta(days=DATE_RANGE_BACK)
    for offset in range(DATE_RANGE_BACK + DATE_RANGE_FORWARD + 1):
        day = start + timedelta(days=offset)
        bookings = await reports.bookings_for_day(
            session, day, include_cancelled=True
        )
        if bookings:
            days.append((day, len(bookings)))
    if days:
        text = (
            "<b>🧾 Записи</b>\n\n"
            "Выберите день. В списке есть и отменённые записи."
        )
    else:
        text = (
            "<b>🧾 Записи</b>\n\n"
            "Записей пока нет. Когда клиенты запишутся, дни появятся здесь."
        )
    await edit_or_send(callback, text, bookings_dates(days))


async def _render_list(callback: CallbackQuery, session, day_date: date) -> None:
    bookings = await reports.bookings_for_day(
        session, day_date, include_cancelled=True
    )
    previous, following = await reports.booking_neighbour_dates(session, day_date)
    await edit_or_send(
        callback,
        admin_bookings_text(day_date, bookings),
        bookings_list(
            bookings,
            day_date,
            previous or day_date - timedelta(days=1),
            following or day_date + timedelta(days=1),
        ),
    )


async def _render_card(callback: CallbackQuery, session, booking_id: int) -> None:
    booking = await bookings_service.load_booking(session, booking_id)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await edit_or_send(
        callback,
        booking_card_text(booking, admin=True),
        booking_card(booking),
    )


@router.callback_query(AdminCb.filter(F.section == "bookings"))
async def bookings_root(callback: CallbackQuery, session) -> None:
    await callback.answer()
    await _render_dates(callback, session)


@router.callback_query(ABookCb.filter())
async def on_booking_action(
    callback: CallbackQuery, callback_data: ABookCb, session
) -> None:
    action = callback_data.action

    if action == "dates":
        await callback.answer()
        await _render_dates(callback, session)
        return

    if action == "list":
        day_date = _parse_date(callback_data.date) or today()
        await callback.answer()
        await _render_list(callback, session, day_date)
        return

    booking = await bookings_service.load_booking(session, callback_data.booking_id)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    if action == "card":
        await callback.answer()
        await edit_or_send(
            callback, booking_card_text(booking, admin=True), booking_card(booking)
        )
        return

    if action == "cancel":
        await callback.answer()
        await edit_or_send(
            callback,
            f"Отменить запись №{booking.id} "
            f"({fmt_date_long(booking.start_at.date())})?\n\n"
            "Клиент получит уведомление.",
            admin_cancel_confirm(booking),
        )
        return

    if action == "cancel_yes":
        try:
            booking = await bookings_service.cancel_booking(
                session,
                booking.id,
                reason="admin_cancelled",
                by_client=False,
            )
        except BookingError as error:
            await callback.answer(str(error), show_alert=True)
            return
        if booking.client is not None and callback.bot is not None:
            await safe_send(
                callback.bot,
                booking.client.tg_id,
                f"❌ <b>Запись №{booking.id} отменена студией.</b>\n\n"
                f"{fmt_date_long(booking.start_at.date())}, "
                f"{booking.start_at.strftime('%H:%M')}.\n"
                "Если это ошибка или нужно другое время — свяжитесь с нами.",
            )
        await callback.answer("Запись отменена")
        await edit_or_send(
            callback, booking_card_text(booking, admin=True), booking_card(booking)
        )
        return

    if action in {"complete", "no_show"}:
        status = (
            BookingStatus.COMPLETED
            if action == "complete"
            else BookingStatus.NO_SHOW
        )
        try:
            booking = await bookings_service.mark_status(session, booking.id, status)
        except BookingError as error:
            await callback.answer(str(error), show_alert=True)
            return
        await callback.answer(
            "Визит завершён"
            if status == BookingStatus.COMPLETED
            else "Отмечено: не пришёл"
        )
        await edit_or_send(
            callback, booking_card_text(booking, admin=True), booking_card(booking)
        )
        return

    await callback.answer("Действие пока недоступно", show_alert=True)

