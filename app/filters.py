from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.config import settings


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, db_user=None) -> bool:
        if db_user is not None and getattr(db_user, "is_admin", False):
            return True
        user = getattr(event, "from_user", None)
        return bool(user and user.id in settings.admin_id_set)
