from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def edit_or_send(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует сообщение, под которым нажата кнопка, либо отправляет новое."""
    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return
            logger.debug("Не удалось отредактировать сообщение: %s", error)
    if callback.bot is not None:
        await callback.bot.send_message(
            callback.from_user.id, text, reply_markup=reply_markup
        )


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            logger.debug("Не удалось отредактировать сообщение: %s", error)
