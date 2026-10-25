from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.client import (
    PAGE_SIZE,
    back_to_menu,
    categories_kb,
    service_card_kb,
    services_kb,
)
from app.bot.texts import catalog_text, service_text
from app.callbacks import CatCb, NavCb, PickSvcCb, SvcCb
from app.db.models import User
from app.services import bookings as bookings_service
from app.services import catalog as catalog_service
from app.services.bookings import BookingError
from app.states import BookingFlow
from app.utils.ui import edit_or_send

router = Router(name="catalog")


async def show_categories_callback(
    callback: CallbackQuery,
    session,
    db_user: User | None,
    *,
    mode: str,
) -> None:
    categories = await catalog_service.active_categories(session)
    counts = await catalog_service.category_service_counts(session)
    if not categories:
        await callback.answer()
        await edit_or_send(
            callback,
            "Прайс пока пуст. Загляните чуть позже.",
            back_to_menu(),
        )
        return
    await callback.answer()
    await edit_or_send(
        callback,
        catalog_text(None, mode),
        categories_kb(categories, counts, mode),
    )


async def show_categories_message(
    message: Message, session, db_user: User | None, *, mode: str = "view"
) -> None:
    categories = await catalog_service.active_categories(session)
    counts = await catalog_service.category_service_counts(session)
    if not categories:
        await message.answer(
            "Прайс пока пуст. Загляните чуть позже.", reply_markup=back_to_menu()
        )
        return
    await message.answer(
        catalog_text(None, mode),
        reply_markup=categories_kb(categories, counts, mode),
        parse_mode="HTML",
    )


async def show_category(
    callback: CallbackQuery,
    session,
    *,
    category_id: int,
    mode: str,
    page: int,
) -> None:
    category = await catalog_service.get_category(session, category_id)
    if category is None or not category.is_active:
        await callback.answer("Раздел недоступен", show_alert=True)
        return

    services = await catalog_service.services_by_category(session, category.id)
    total = len(services)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    page_services = services[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    has_next = page + 1 < pages
    back_to = NavCb(to="book" if mode == "book" else "price")

    if not services:
        await callback.answer()
        await edit_or_send(
            callback,
            f"<b>{category.emoji} {category.title}</b>\n\n"
            "В этом разделе пока нет услуг.",
            services_kb([], category.id, mode, page, False, back_to),
        )
        return

    text = catalog_text(category, mode)
    if pages > 1:
        text += f"\n\nСтраница {page + 1} из {pages}."
    await callback.answer()
    await edit_or_send(
        callback,
        text,
        services_kb(
            page_services,
            category.id,
            mode,
            page,
            has_next,
            back_to,
        ),
    )


@router.callback_query(CatCb.filter())
async def on_category(
    callback: CallbackQuery, callback_data: CatCb, session
) -> None:
    await show_category(
        callback,
        session,
        category_id=callback_data.cid,
        mode=callback_data.mode,
        page=callback_data.page,
    )


@router.callback_query(SvcCb.filter())
async def on_service(
    callback: CallbackQuery, callback_data: SvcCb, session
) -> None:
    service = await catalog_service.get_service(session, callback_data.sid)
    if service is None or not service.is_active:
        await callback.answer("Услуга больше недоступна", show_alert=True)
        return
    category = await catalog_service.get_category(session, service.category_id)
    if category is None or not category.is_active:
        await callback.answer("Раздел услуги недоступен", show_alert=True)
        return
    await callback.answer()
    await edit_or_send(
        callback,
        service_text(service, callback_data.mode),
        service_card_kb(
            service,
            callback_data.mode,
            category.id,
            callback_data.page,
        ),
    )


@router.callback_query(PickSvcCb.filter())
async def on_pick_service(
    callback: CallbackQuery,
    callback_data: PickSvcCb,
    session,
    state,
    db_user: User | None,
) -> None:
    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    service = await catalog_service.get_service(session, callback_data.sid)
    if service is None or not service.is_active:
        await callback.answer("Услуга больше недоступна", show_alert=True)
        return

    if callback_data.mode == "add":
        draft = await bookings_service.get_active_draft(session, db_user.id)
        if draft is None:
            await callback.answer(
                "Черновик уже истёк. Начните запись заново.", show_alert=True
            )
            return
        try:
            booking = await bookings_service.append_service(
                session, draft.id, service
            )
        except BookingError as error:
            await callback.answer(str(error), show_alert=True)
            return
        await state.set_state(None)
        await state.update_data(booking_id=booking.id, mode="book")
        await callback.answer("Услуга добавлена")
        from app.bot.routers.booking import render_draft

        await render_draft(callback, session, db_user, state)
        return

    active = await bookings_service.get_active_draft(session, db_user.id)
    if active is not None:
        await bookings_service.clear_draft(session, active.id, reason="new_booking")

    await state.set_state(BookingFlow.pick_date)
    await state.update_data(
        mode="book",
        service_ids=[service.id],
        booking_id=0,
        date_offset=0,
    )
    await callback.answer()
    from app.bot.routers.booking import show_date_picker

    await show_date_picker(
        callback,
        session,
        state,
        mode="book",
        back_callback=NavCb(to="book"),
    )
