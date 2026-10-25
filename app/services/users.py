from __future__ import annotations

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def upsert_user(
    session: AsyncSession,
    tg_user: TgUser,
    *,
    is_admin: bool | None = None,
) -> User:
    user = await get_user(session, tg_user.id)
    if user is None:
        user = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            is_admin=bool(is_admin if is_admin is not None else tg_user.id in settings.admin_id_set),
        )
        session.add(user)
    else:
        user.username = tg_user.username
        if tg_user.full_name:
            user.full_name = tg_user.full_name
        if is_admin is not None:
            user.is_admin = is_admin
        elif tg_user.id in settings.admin_id_set:
            user.is_admin = True
    await session.commit()
    return user


async def set_phone(session: AsyncSession, user: User, phone: str) -> None:
    user.phone = phone
    await session.commit()
