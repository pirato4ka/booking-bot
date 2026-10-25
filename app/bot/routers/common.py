from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.keyboards.client import back_to_menu, main_menu
from app.bot.texts import about_text, main_menu_text
from app.callbacks import NavCb
from app.config import settings
from app.db.models import User
from app.services import bookings as bookings_service
from app.services.users import upsert_user
from app.states import BookingFlow
from app.utils.ui import edit_or_send

router = Router(name="common")
# Команды регистрируются до FSM-обработчиков, иначе «/start» или «/cancel»
# в состоянии ввода телефона будут приняты за текст ответа.
commands_router = Router(name="commands")


def is_admin(user: User | None) -> bool:
    if user is not None and user.is_admin:
        return True
    return False


async def show_main(
    callback: CallbackQuery,
    session,
    db_user: User | None,
    state,
) -> None:
    await state.clear()
    user = db_user
    if user is None and callback.from_user is not None:
        user = await upsert_user(session, callback.from_user)
    await edit_or_send(
        callback,
        main_menu_text(is_admin(user)),
        main_menu(is_admin(user)),
    )


@commands_router.message(CommandStart())
async def cmd_start(message: Message, state, session, db_user: User | None) -> None:
    await state.clear()
    user = db_user or await upsert_user(session, message.from_user)
    await message.answer(
        main_menu_text(is_admin(user)),
        reply_markup=main_menu(is_admin(user)),
        parse_mode="HTML",
    )


@commands_router.message(Command("help"))
async def cmd_help(message: Message, state) -> None:
    await state.clear()
    await message.answer(about_text(), reply_markup=back_to_menu(), parse_mode="HTML")


@commands_router.message(Command("price"))
async def cmd_price(message: Message, session, db_user: User | None, state) -> None:
    from app.bot.routers.catalog import show_categories_message

    await state.clear()
    await show_categories_message(message, session, db_user)


@commands_router.message(Command("book"))
async def cmd_book(message: Message, session, db_user: User | None, state) -> None:
    from app.bot.routers.catalog import show_categories_message

    await state.clear()
    await show_categories_message(message, session, db_user, mode="book")


@commands_router.message(Command("my"))
async def cmd_my(
    message: Message, session, db_user: User | None, state
) -> None:
    from app.bot.routers.my import render_my_list_message

    await state.clear()
    if db_user is None:
        await message.answer("Не удалось определить пользователя. Нажмите /start.")
        return
    await render_my_list_message(message, session, db_user)


@commands_router.message(Command("cancel"))
async def cmd_cancel(
    message: Message, state, session, db_user: User | None
) -> None:
    current = await state.get_state()
    if current and current.startswith(BookingFlow.__name__) and db_user is not None:
        draft = await bookings_service.get_active_draft(session, db_user.id)
        if draft is not None:
            await bookings_service.clear_draft(session, draft.id)

    await state.clear()
    await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    user = db_user or (await upsert_user(session, message.from_user) if message.from_user else None)
    await message.answer(
        main_menu_text(is_admin(user)),
        reply_markup=main_menu(is_admin(user)),
        parse_mode="HTML",
    )


@router.callback_query(NavCb.filter(F.to == "main"))
async def nav_main(
    callback: CallbackQuery, state, session, db_user: User | None
) -> None:
    await callback.answer()
    await show_main(callback, session, db_user, state)


@router.callback_query(NavCb.filter(F.to == "about"))
async def nav_about(callback: CallbackQuery) -> None:
    await callback.answer()
    await edit_or_send(callback, about_text(), back_to_menu())


@router.callback_query(NavCb.filter(F.to == "price"))
async def nav_price(callback: CallbackQuery, session, db_user: User | None) -> None:
    from app.bot.routers.catalog import show_categories_callback

    await show_categories_callback(callback, session, db_user, mode="view")


@router.callback_query(NavCb.filter(F.to == "book"))
async def nav_book(callback: CallbackQuery, session, db_user: User | None) -> None:
    from app.bot.routers.catalog import show_categories_callback

    await show_categories_callback(callback, session, db_user, mode="book")


@router.callback_query(NavCb.filter(F.to == "my"))
async def nav_my(callback: CallbackQuery, session, db_user: User | None) -> None:
    from app.bot.routers.my import render_my_list_callback

    if db_user is None:
        await callback.answer("Нажмите /start", show_alert=True)
        return
    await render_my_list_callback(callback, session, db_user)


@router.callback_query(NavCb.filter(F.to == "admin"))
async def nav_admin(
    callback: CallbackQuery, session, db_user: User | None
) -> None:
    from app.bot.routers.admin.menu import render_admin_menu

    if not is_admin(db_user) and (
        callback.from_user.id not in settings.admin_id_set
    ):
        await callback.answer("Раздел доступен только администратору", show_alert=True)
        return
    await callback.answer()
    await render_admin_menu(callback, session)


@router.message()
async def fallback(message: Message, db_user: User | None) -> None:
    await message.answer(
        "Не понял команду. Воспользуйтесь меню ниже.",
        reply_markup=main_menu(is_admin(db_user)),
        parse_mode="HTML",
    )
