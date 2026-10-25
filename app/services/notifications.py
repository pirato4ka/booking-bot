from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from app.config import settings

logger = logging.getLogger(__name__)


async def safe_send(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Отправляет сообщение, не роняя обработчик при блокировке бота."""
    try:
        await bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        return True
    except TelegramAPIError as error:
        logger.warning("Не удалось отправить сообщение %s: %s", chat_id, error)
        return False


async def notify_admins(
    bot: Bot,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    sent = 0
    for admin_id in sorted(settings.admin_id_set):
        if await safe_send(bot, admin_id, text, reply_markup):
            sent += 1
    return sent
