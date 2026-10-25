from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.client import (
    back_to_menu,
    cancel_confirm_kb,
    draft_kb,
    my_card_kb,
    my_list_kb,
)
from app.bot.texts import booking_card_text, my_bookings_text
from app.callbacks import MyCb
from app.config import settings
from app.db.models import Booking, BookingStatus, User
from app.services import bookings as bookings_service
from app.services import reports
from app.services.bookings import BookingError
from app.services.notifications import notify_admins
from app.states import BookingFlow
from app.utils.timeutil import fmt_duration, tz_now
from app.utils.ui import edit_or_send

router = Router(name="my")


async def _owned(
    session, booking_id: int, db_user: User, *, required: bool = True
) -> Booking | None:
    booking = await bookings_service.load_booking(session, booking_id)
    if booking is None or booking.client_id != db_user.id:
        if required:
            raise BookingError("Запись не найдена")
        return None
    return booking


async def _load_history(session, db_user: User) -> list[Booking]:
    draft = await bookings_service.get_active_draft(session, db_user.id)
    future = await reports.client_future_bookings(session, db_user.id)
    past = await reports.client_past_bookings(session, db_user.id, limit=10)
    bookings: list[Booking] = []
    seen: set[int] = set()
    for booking in ([draft] if draft else []) + future + past:
        if booking.id not in seen:
            seen.add(booking.id)
            bookings.append(booking)
    return bookings


async def render_my_list_callback(
    callback: CallbackQuery, session, db_user: User
) -> None:
    bookings = await _load_history(session, db_user)
    await callback.answer()
    await edit_or_send(
        callback,
        my_bookings_text(bookings),
        my_list_kb(bookings),
    )


async def render_my_list_message(
    message: Message, session, db_user: User
) -> None:
    bookings = await _load_history(session, db_user)
    await message.answer(
        my_bookings_text(bookings),
        reply_markup=my_list_kb(bookings),
        parse_mode="HTML",
    )


async def render_booking_card(
    callback: CallbackQuery, session, db_user: User, booking_id: int
) -> None:
    try:
        booking = await _owned(session, booking_id, db_user)
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        return

    now = tz_now()
    markup = draft_kb() if booking.status == BookingStatus.DRAFT else my_card_kb(booking, now)
    text = booking_card_text(booking)
    if booking.status == BookingStatus.CONFIRMED and booking.start_at >= now:
        minutes_left = max(1, int((booking.start_at - now).total_seconds() // 60))
        text += (
            f"\n\n🗓 До визита: {fmt_duration(minutes_left)}"
            f"\nОтменить или перенести можно не позднее чем за "
            f"{settings.cancel_cutoff_hours} ч."
        )
    await callback.answer()
    await edit_or_send(callback, text, markup)


@router.callback_query(MyCb.filter(F.action == "list"))
async def my_list(callback: CallbackQuery, session, db_user: User | None) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    await render_my_list_callback(callback, session, db_user)


@router.callback_query(MyCb.filter(F.action == "card"))
async def my_card(
    callback: CallbackQuery, callback_data: MyCb, session, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    await render_booking_card(callback, session, db_user, callback_data.booking_id)


@router.callback_query(MyCb.filter(F.action == "cancel"))
async def my_cancel(
    callback: CallbackQuery, callback_data: MyCb, session, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    try:
        booking = await _owned(session, callback_data.booking_id, db_user)
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        return

    await callback.answer()
    await edit_or_send(
        callback,
        f"<b>Отменить запись №{booking.id}?</b>\n\n"
        "Слот снова станет доступен другим клиентам.",
        cancel_confirm_kb(booking.id),
    )


@router.callback_query(MyCb.filter(F.action == "cancel_yes"))
async def my_cancel_yes(
    callback: CallbackQuery, callback_data: MyCb, session, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    try:
        await _owned(session, callback_data.booking_id, db_user)
        booking = await bookings_service.cancel_booking(
            session,
            callback_data.booking_id,
            reason="client_cancelled",
            by_client=True,
        )
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        return

    await callback.answer("Запись отменена")
    await edit_or_send(
        callback,
        f"❌ <b>Запись №{booking.id} отменена.</b>\n\n"
        "Если понадобится другое время — будем рады помочь.",
        back_to_menu(),
    )
    await notify_admins(
        callback.bot,
        f"❌ <b>Клиент отменил запись</b>\n\n{booking_card_text(booking, admin=True)}",
    )


@router.callback_query(MyCb.filter(F.action == "move"))
async def my_move(
    callback: CallbackQuery, callback_data: MyCb, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    try:
        booking = await _owned(session, callback_data.booking_id, db_user)
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        return
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.DRAFT):
        await callback.answer("Эту запись уже нельзя перенести", show_alert=True)
        return

    await state.set_state(BookingFlow.pick_date)
    await state.update_data(
        mode="move",
        booking_id=booking.id,
        service_ids=[],
        date_offset=0,
    )
    await callback.answer()
    from app.bot.routers.booking import show_date_picker

    await show_date_picker(
        callback,
        session,
        state,
        mode="move",
        back_callback=MyCb(action="card", booking_id=booking.id),
    )


@router.callback_query(MyCb.filter(F.action == "ack"))
async def my_ack(
    callback: CallbackQuery, callback_data: MyCb, session, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    try:
        booking = await _owned(session, callback_data.booking_id, db_user)
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        return

    ok = await bookings_service.mark_client_confirmed(session, booking.id)
    if not ok:
        await callback.answer("Подтвердить визит уже нельзя", show_alert=True)
        return
    booking = await bookings_service.load_booking(session, booking.id) or booking
    await callback.answer("Спасибо! Ждём вас ❤️")
    await edit_or_send(
        callback,
        booking_card_text(booking) + "\n\n✅ <b>Визит подтверждён. Спасибо!</b>",
        my_card_kb(booking, tz_now()),
    )
    await notify_admins(
        callback.bot,
        f"✅ <b>Клиент подтвердил визит</b>\n\n{booking_card_text(booking, admin=True)}",
    )


@router.callback_query(MyCb.filter(F.action == "decline"))
async def my_decline(callback: CallbackQuery) -> None:
    await callback.answer("Если планы изменились, отмените запись в карточке.")
