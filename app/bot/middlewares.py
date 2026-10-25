from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update
from aiogram.types import User as TgUser

from app.db import SessionLocal
from app.services.users import upsert_user

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Одна сессия БД на один update."""

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        async with SessionLocal() as session:
            data["session"] = session
            return await handler(event, data)


def _extract_user(event: Update) -> TgUser | None:
    for attribute in (
        "message",
        "edited_message",
        "callback_query",
        "inline_query",
        "pre_checkout_query",
    ):
        payload = getattr(event, attribute, None)
        user = getattr(payload, "from_user", None)
        if user is not None:
            return user
    return None


class UserMiddleware(BaseMiddleware):
    """Создаёт/обновляет пользователя и кладёт его в data["db_user"]."""

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        session = data.get("session")
        tg_user = data.get("event_from_user") or _extract_user(event)
        if session is not None and tg_user is not None and not tg_user.is_bot:
            try:
                data["db_user"] = await upsert_user(session, tg_user)
            except Exception:  # noqa: BLE001 - не блокируем обработку événement
                logger.exception("Не удалось обновить пользователя %s", tg_user.id)
        return await handler(event, data)
