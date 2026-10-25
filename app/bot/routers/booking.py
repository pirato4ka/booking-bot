from __future__ import annotations

from datetime import date, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from app.bot.keyboards.client import (
    back_to_menu,
    booking_success_kb,
    comment_kb,
    date_picker_kb,
    draft_confirm_kb,
    draft_kb,
    phone_keyboard,
    slots_kb,
)
from app.bot.texts import (
    booking_card_text,
    booking_success_text,
    draft_contact_text,
    draft_text,
)
from app.callbacks import DateCb, DraftCb, MyCb, NavCb, SlotCb
from app.config import settings
from app.db.models import Booking, BookingStatus, User
from app.services import availability
from app.services import bookings as bookings_service
from app.services import catalog as catalog_service
from app.services.bookings import BookingError
from app.services.notifications import notify_admins
from app.services.users import set_phone
from app.states import BookingFlow
from app.utils.parsing import normalize_phone, parse_comment
from app.utils.text import esc
from app.utils.timeutil import fmt_date_long, fmt_duration, today, tz_now
from app.utils.ui import edit_or_send

router = Router(name="booking")


def _iso_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


async def _services_from_state(session, state) -> list:
    data = await state.get_data()
    ids = [int(value) for value in data.get("service_ids", [])]
    services = await catalog_service.active_services_by_ids(session, ids)
    if not services:
        raise BookingError("Услуги больше недоступны. Начните запись заново.")
    return services


async def _required_minutes(session, state, data: dict | None = None) -> int:
    data = data or await state.get_data()
    if data.get("mode") == "book":
        services = await _services_from_state(session, state)
        return availability.required_minutes_for_services(services)
    booking_id = int(data.get("booking_id") or 0)
    booking = await bookings_service.load_booking(session, booking_id)
    if booking is None:
        raise BookingError("Запись не найдена. Начните заново.")
    return availability.required_minutes_for_booking(booking)


async def _load_owned(session, booking_id: int, client_id: int) -> Booking:
    booking = await bookings_service.load_booking(session, booking_id)
    if booking is None or booking.client_id != client_id:
        raise BookingError("Запись не найдена")
    return booking


async def _current_draft(session, state, db_user: User) -> Booking | None:
    data = await state.get_data()
    booking_id = int(data.get("booking_id") or 0)
    if booking_id:
        booking = await _load_owned(session, booking_id, db_user.id)
        if booking.status == BookingStatus.DRAFT and not bookings_service.is_draft_expired(
            booking
        ):
            return booking
    return await bookings_service.get_active_draft(session, db_user.id)


async def _ask_phone(message: Message, state, booking_id: int) -> None:
    await state.set_state(BookingFlow.phone)
    await state.update_data(booking_id=booking_id)
    await message.answer(
        "<b>📱 Телефон для связи</b>\n\n"
        "Отправьте номер кнопкой ниже или введите его вручную.",
        reply_markup=phone_keyboard(),
        parse_mode="HTML",
    )


async def _ask_name(message: Message, state) -> None:
    await state.set_state(BookingFlow.name)
    await message.answer(
        "<b>✍️ Как к вам обращаться?</b>\n\n"
        "Напишите имя — администратор увидит его в записи.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )


async def _ask_comment(message: Message, state, booking_id: int) -> None:
    await state.set_state(BookingFlow.comment)
    await state.update_data(booking_id=booking_id)
    await message.answer(
        "<b>💬 Комментарий к записи</b>\n\n"
        "Напишите пожелания или вопрос. Если нечего добавить — пропустите.",
        reply_markup=comment_kb(),
        parse_mode="HTML",
    )


async def show_date_picker(
    callback: CallbackQuery,
    session,
    state,
    *,
    mode: str,
    back_callback=None,
    offset: int = 0,
    page_size: int = 7,
) -> None:
    data = await state.get_data()
    try:
        required = await _required_minutes(session, state, data)
    except BookingError as error:
        await state.clear()
        await edit_or_send(callback, str(error), back_to_menu())
        return

    booking_id = int(data.get("booking_id") or 0)
    exclude_id = booking_id if mode in ("move", "edit_time") else None
    days = await availability.available_days(
        session,
        required,
        today(),
        settings.schedule_horizon_days,
        exclude_booking_id=exclude_id,
    )
    offset = max(0, offset - offset % page_size)
    page_days = days[offset : offset + page_size]
    back_callback = back_callback or NavCb(to="book")

    if not days:
        await state.update_data(date_offset=0)
        await edit_or_send(
            callback,
            "<b>Пока нет свободных окон</b>\n\n"
            f"На ближайшие {settings.schedule_horizon_days} дней всё занято. "
            "Попробуйте позже или свяжитесь со студией.",
            _back_markup(back_callback),
        )
        return

    await state.update_data(date_offset=offset)
    title = "Выберите новую дату" if mode == "move" else "Выберите дату"
    text = (
        f"<b>🗓 {title}</b>\n\n"
        f"Длительность визита: {fmt_duration(required)}.\n"
        "Показаны только дни со свободными слотами."
    )
    if offset:
        text += f"\n\nДни {offset + 1}–{min(offset + page_size, len(days))} из {len(days)}."
    await edit_or_send(
        callback,
        text,
        date_picker_kb(page_days, offset, back_callback, page_size=page_size),
    )


def _back_markup(back_callback) -> InlineKeyboardMarkup:
    from app.bot.keyboards.client import btn

    return InlineKeyboardMarkup(inline_keyboard=[[btn("⬅️ Назад", back_callback)]])

def _back_for(data: dict):
    mode = data.get("mode")
    if mode == "move":
        return MyCb(action="card", booking_id=int(data.get("booking_id") or 0))
    if mode == "edit_time":
        return DraftCb(action="back")
    return NavCb(to="book")


@router.callback_query(DateCb.filter())
async def on_date(
    callback: CallbackQuery, callback_data: DateCb, session, state
) -> None:
    data = await state.get_data()
    mode = data.get("mode", "book")
    back = _back_for(data)

    if not callback_data.date:
        await callback.answer()
        await show_date_picker(
            callback,
            session,
            state,
            mode=mode,
            back_callback=back,
            offset=callback_data.offset,
        )
        return

    day = _iso_date(callback_data.date)
    if day is None:
        await callback.answer("Некорректная дата", show_alert=True)
        return
    try:
        required = await _required_minutes(session, state, data)
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        return

    booking_id = int(data.get("booking_id") or 0)
    exclude_id = booking_id if mode in ("move", "edit_time") else None
    slots = await availability.available_slots(
        session,
        day,
        required,
        exclude_booking_id=exclude_id,
    )
    if not slots:
        await callback.answer(
            "На эту дату уже нет свободного времени. Выберите другой день.",
            show_alert=True,
        )
        await show_date_picker(
            callback,
            session,
            state,
            mode=mode,
            back_callback=back,
            offset=callback_data.offset,
        )
        return

    await state.update_data(selected_date=day.isoformat())
    await callback.answer()
    await edit_or_send(
        callback,
        f"<b>🕐 Свободное время</b>\n\n{fmt_date_long(day)}\n"
        f"Длительность визита: {fmt_duration(required)}.",
        slots_kb(day, slots, callback_data.offset, back),
    )


@router.callback_query(SlotCb.filter())
async def on_slot(
    callback: CallbackQuery,
    callback_data: SlotCb,
    session,
    state,
    db_user: User | None,
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return

    try:
        start_at = datetime.fromisoformat(callback_data.start)
    except ValueError:
        await callback.answer("Некорректное время", show_alert=True)
        return

    data = await state.get_data()
    mode = data.get("mode", "book")

    try:
        if mode == "book":
            services = await _services_from_state(session, state)
            active = await bookings_service.get_active_draft(session, db_user.id)
            if active is not None:
                await bookings_service.clear_draft(
                    session, active.id, reason="new_booking"
                )
            booking = await bookings_service.create_draft(
                session,
                client_id=db_user.id,
                services=services,
                start_at=start_at,
            )
            await state.set_state(BookingFlow.phone)
            await state.update_data(
                mode="book",
                booking_id=booking.id,
                selected_date=start_at.date().isoformat(),
            )
            await callback.answer()
            await edit_or_send(
                callback,
                "⏳ Слот зарезервирован на 10 минут. Заполним контакты.",
            )
            await callback.bot.send_message(
                callback.from_user.id,
                "<b>📱 Телефон для связи</b>\n\n"
                "Отправьте номер кнопкой ниже или введите его вручную.",
                reply_markup=phone_keyboard(),
                parse_mode="HTML",
            )
            return

        if mode == "move":
            booking_id = int(data.get("booking_id") or 0)
            await _load_owned(session, booking_id, db_user.id)
            booking = await bookings_service.reschedule_booking(
                session,
                booking_id,
                start_at,
                by_client=True,
            )
            await state.clear()
            await callback.answer("Запись перенесена")
            await edit_or_send(
                callback,
                booking_card_text(booking) + "\n\n✅ <b>Время изменено.</b>",
                booking_success_kb(),
            )
            await notify_admins(
                callback.bot,
                f"🔁 <b>Клиент перенёс запись</b>\n\n{booking_card_text(booking, admin=True)}",
            )
            return

        booking_id = int(data.get("booking_id") or 0)
        await _load_owned(session, booking_id, db_user.id)
        booking = await bookings_service.reschedule_booking(
            session,
            booking_id,
            start_at,
            by_client=True,
        )
        await state.set_state(None)
        await state.update_data(booking_id=booking.id, mode="book")
        await callback.answer("Время изменено")
        await render_draft(callback, session, db_user, state)
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)


@router.message(BookingFlow.phone)
async def on_phone(
    message: Message, state, session, db_user: User | None
) -> None:
    if db_user is None:
        await message.answer("Нажмите /start и попробуйте снова.")
        return
    try:
        booking = await _current_draft(session, state, db_user)
    except BookingError as error:
        await state.clear()
        await message.answer(str(error), reply_markup=back_to_menu())
        return
    if booking is None:
        await state.clear()
        await message.answer(
            "Время удержания истекло. Начните запись заново.",
            reply_markup=back_to_menu(),
        )
        return

    raw = message.contact.phone_number if message.contact else (message.text or "")
    phone = normalize_phone(raw)
    if phone is None:
        await message.answer(
            "Не удалось распознать номер. Введите телефон в формате "
            "+7 999 123-45-67 или отправьте контакт кнопкой.",
            reply_markup=phone_keyboard(),
        )
        return

    await set_phone(session, db_user, phone)
    await state.update_data(client_phone=phone, booking_id=booking.id)
    await message.answer("✅ Телефон сохранён.", reply_markup=ReplyKeyboardRemove())

    data = await state.get_data()
    name = (data.get("client_name") or booking.client_name or db_user.full_name or "").strip()
    if name:
        await state.update_data(client_name=name)
        await _ask_comment(message, state, booking.id)
    else:
        await _ask_name(message, state)


@router.message(BookingFlow.name)
async def on_name(
    message: Message, state, session, db_user: User | None
) -> None:
    if db_user is None:
        await message.answer("Нажмите /start и попробуйте снова.")
        return
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Имя слишком короткое. Напишите, как к вам обращаться.")
        return
    if len(name) > 128:
        await message.answer("Имя слишком длинное (максимум 128 символов).")
        return

    try:
        booking = await _current_draft(session, state, db_user)
    except BookingError as error:
        await state.clear()
        await message.answer(str(error), reply_markup=back_to_menu())
        return
    if booking is None:
        await state.clear()
        await message.answer(
            "Время удержания истекло. Начните запись заново.",
            reply_markup=back_to_menu(),
        )
        return

    await state.update_data(client_name=name, booking_id=booking.id)
    await message.answer(f"Приятно познакомиться, {esc(name)}!")
    await _ask_comment(message, state, booking.id)


@router.message(BookingFlow.comment)
async def on_comment(
    message: Message, state, session, db_user: User | None
) -> None:
    if db_user is None:
        await message.answer("Нажмите /start и попробуйте снова.")
        return
    try:
        comment = parse_comment(message.text or "")
    except ValueError as error:
        await message.answer(str(error), reply_markup=comment_kb())
        return

    try:
        booking = await _current_draft(session, state, db_user)
    except BookingError as error:
        await state.clear()
        await message.answer(str(error), reply_markup=back_to_menu())
        return
    if booking is None:
        await state.clear()
        await message.answer(
            "Время удержания истекло. Начните запись заново.",
            reply_markup=back_to_menu(),
        )
        return

    data = await state.get_data()
    name = data.get("client_name") or booking.client_name or db_user.full_name
    phone = data.get("client_phone") or booking.client_phone or db_user.phone or ""
    await state.update_data(client_comment=comment, booking_id=booking.id)
    await state.set_state(None)
    await message.answer(
        draft_contact_text(booking, name, phone, comment),
        reply_markup=draft_confirm_kb(),
        parse_mode="HTML",
    )



async def render_draft(
    callback: CallbackQuery, session, db_user: User, state
) -> None:
    try:
        booking = await _current_draft(session, state, db_user)
    except BookingError as error:
        await state.clear()
        await edit_or_send(callback, str(error), back_to_menu())
        return
    if booking is None:
        await state.clear()
        await edit_or_send(
            callback,
            "Черновик не найден или время удержания истекло. Начните запись заново.",
            back_to_menu(),
        )
        return

    await state.set_state(None)
    await state.update_data(booking_id=booking.id, mode="book")
    data = await state.get_data()
    text = draft_text(booking, tz_now())
    if data.get("client_phone"):
        text += (
            f"\n\n<b>Телефон:</b> {esc(data['client_phone'])}"
            f"\n<b>Имя:</b> {esc(data.get('client_name') or '—')}"
        )
    await edit_or_send(callback, text, draft_kb())


@router.callback_query(DraftCb.filter(F.action == "ask_confirm"))
async def draft_ask_confirm(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    booking = await _current_draft(session, state, db_user)
    if booking is None:
        await callback.answer(
            "Черновик истёк. Начните запись заново.", show_alert=True
        )
        return
    data = await state.get_data()
    name = (data.get("client_name") or booking.client_name or "").strip()
    phone = data.get("client_phone") or booking.client_phone or ""

    if not phone:
        await callback.answer()
        await _ask_phone(callback.message, state, booking.id)
        return
    if not name:
        await callback.answer()
        await _ask_name(callback.message, state)
        return

    await state.update_data(
        booking_id=booking.id,
        client_name=name,
        client_phone=phone,
        client_comment=data.get("client_comment", ""),
    )
    await callback.answer()
    await edit_or_send(
        callback,
        draft_contact_text(booking, name, phone, data.get("client_comment", "")),
        draft_confirm_kb(),
    )


@router.callback_query(DraftCb.filter(F.action == "confirm"))
async def draft_confirm(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    data = await state.get_data()
    booking_id = int(data.get("booking_id") or 0)
    if not booking_id:
        await callback.answer("Черновик не найден", show_alert=True)
        return

    name = (data.get("client_name") or "").strip()
    phone = data.get("client_phone") or ""
    if not name or not phone:
        await callback.answer(
            "Не хватает имени или телефона. Вернитесь назад и заполните контакты.",
            show_alert=True,
        )
        return

    await callback.answer("Оформляем запись…")
    try:
        await _load_owned(session, booking_id, db_user.id)
        booking = await bookings_service.confirm_booking(
            session,
            booking_id,
            client_name=name,
            client_phone=phone,
            comment=data.get("client_comment", ""),
        )
    except BookingError as error:
        await state.clear()
        await edit_or_send(callback, str(error), back_to_menu())
        return

    await state.clear()
    await edit_or_send(
        callback,
        booking_success_text(booking),
        booking_success_kb(),
    )
    await notify_admins(
        callback.bot,
        f"🆕 <b>Новая запись</b>\n\n{booking_card_text(booking, admin=True)}",
    )



@router.callback_query(DraftCb.filter(F.action == "back"))
async def draft_back(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    await callback.answer()
    await render_draft(callback, session, db_user, state)


@router.callback_query(DraftCb.filter(F.action == "add"))
async def draft_add(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    booking = await _current_draft(session, state, db_user)
    if booking is None:
        await callback.answer(
            "Черновик истёк. Начните запись заново.", show_alert=True
        )
        return

    from app.bot.routers.catalog import show_categories_callback

    await state.set_state(None)
    await state.update_data(booking_id=booking.id, mode="book")
    await show_categories_callback(callback, session, db_user, mode="add")


@router.callback_query(DraftCb.filter(F.action == "time"))
async def draft_time(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    booking = await _current_draft(session, state, db_user)
    if booking is None:
        await callback.answer(
            "Черновик истёк. Начните запись заново.", show_alert=True
        )
        return

    await state.set_state(BookingFlow.pick_date)
    await state.update_data(
        mode="edit_time",
        booking_id=booking.id,
        service_ids=[],
        date_offset=0,
    )
    await callback.answer()
    await show_date_picker(
        callback,
        session,
        state,
        mode="edit_time",
        back_callback=DraftCb(action="back"),
    )


@router.callback_query(DraftCb.filter(F.action == "clear"))
async def draft_clear(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    booking = await _current_draft(session, state, db_user)
    if booking is not None:
        await bookings_service.clear_draft(
            session, booking.id, reason="client_cancelled"
        )
    await state.clear()
    await callback.answer("Запись отменена")
    await edit_or_send(
        callback,
        "🗑 Черновик удалён. Слот снова свободен.",
        back_to_menu(),
    )


@router.callback_query(DraftCb.filter(F.action == "edit_phone"))
async def draft_edit_phone(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    booking = await _current_draft(session, state, db_user)
    if booking is None:
        await callback.answer(
            "Черновик истёк. Начните запись заново.", show_alert=True
        )
        return
    await callback.answer()
    await _ask_phone(callback.message, state, booking.id)


@router.callback_query(DraftCb.filter(F.action == "skip_comment"))
async def draft_skip_comment(
    callback: CallbackQuery, session, state, db_user: User | None
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    booking = await _current_draft(session, state, db_user)
    if booking is None:
        await callback.answer(
            "Время удержания истекло. Начните запись заново.", show_alert=True
        )
        return

    data = await state.get_data()
    name = data.get("client_name") or booking.client_name or db_user.full_name
    phone = data.get("client_phone") or booking.client_phone or db_user.phone or ""
    await state.update_data(client_comment="", booking_id=booking.id)
    await state.set_state(None)
    await callback.answer()
    await edit_or_send(
        callback,
        draft_contact_text(booking, name, phone, ""),
        draft_confirm_kb(),
    )
