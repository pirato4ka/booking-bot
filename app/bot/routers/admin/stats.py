from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.admin_texts import stats_text
from app.bot.keyboards.admin import stats_kb
from app.callbacks import AdminCb
from app.filters import IsAdmin
from app.services import reports
from app.utils.ui import edit_or_send

router = Router(name="admin_stats")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


@router.callback_query(AdminCb.filter(F.section == "stats"))
async def stats_root(callback: CallbackQuery, session) -> None:
    stats = await reports.admin_stats(session)
    await callback.answer()
    await edit_or_send(callback, stats_text(stats), stats_kb())
