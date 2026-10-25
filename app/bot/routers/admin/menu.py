from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.admin_texts import admin_menu_text
from app.bot.keyboards.admin import admin_back, admin_menu
from app.callbacks import AdminCb
from app.filters import IsAdmin
from app.services import reports
from app.utils.ui import edit_or_send

router = Router(name="admin_menu")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


async def render_admin_menu(callback: CallbackQuery, session) -> None:
    stats = await reports.admin_stats(session)
    await edit_or_send(callback, admin_menu_text(stats), admin_menu())


@router.callback_query(AdminCb.filter(F.section == "menu"))
async def admin_menu_handler(callback: CallbackQuery, session) -> None:
    await callback.answer()
    await render_admin_menu(callback, session)


@router.callback_query(AdminCb.filter(F.section == "help"))
async def admin_help_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    await edit_or_send(
        callback,
        "<b>Подсказка</b>\n\n"
        "• Расписание — окна работы и публикация дней.\n"
        "• Услуги — цены, длительность и видимость в прайсе.\n"
        "• Записи — карточки клиентов и статусы визитов.\n"
        "• Статистика — загрузка и выручка.\n\n"
        "Если что-то не получается, вернитесь в админ-меню.",
        admin_back(),
    )
