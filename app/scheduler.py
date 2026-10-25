from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.bot.keyboards.client import btn
from app.callbacks import MyCb
from app.config import settings
from app.db import SessionLocal
from app.db.models import Booking, BookingStatus
from app.services.bookings import expire_stale_drafts
from app.services.notifications import safe_send
from app.utils.timeutil import fmt_date_long, fmt_time, tz_now

logger = logging.getLogger(__name__)


def _reminder_text(booking: Booking, hours: int) -> str:
    title = (
        "⏰ <b>Напоминаем о визите</b>"
        if hours > 3
        else "⏰ <b>Визит совсем скоро</b>"
    )
    now = tz_now()
    if booking.start_at.date() == now.date():
        prefix = "сегодня"
    elif booking.start_at.date() == (now + timedelta(days=1)).date():
        prefix = "завтра"
    else:
        prefix = fmt_date_long(booking.start_at.date())
    services = ", ".join(item.title for item in booking.items[:3])
    if len(booking.items) > 3:
        services += " и ещё"
    lines = [
        title,
        "",
        f"{prefix.capitalize() if prefix in {'сегодня', 'завтра'} else prefix} "
        f"в <b>{fmt_time(booking.start_at)}</b>.",
        f"Запись №{booking.id}",
    ]
    if services:
        lines.append(f"Услуги: {services}")
    if settings.studio_address:
        lines.extend(["", f"📍 {settings.studio_address}"])
    lines.extend(
        [
            "",
            "Подтвердите визит или предупредите, если планы изменились.",
        ]
    )
    return "\n".join(lines)


def _reminder_markup(booking: Booking) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("✅ Подтверждаю", MyCb(action="ack", booking_id=booking.id))],
            [btn("❌ Не смогу прийти", MyCb(action="decline", booking_id=booking.id))],
        ]
    )


async def expire_drafts_job() -> None:
    async with SessionLocal() as session:
        count = await expire_stale_drafts(session)
    if count:
        logger.info("Освобождено просроченных удержаний: %s", count)


async def send_reminders_job(bot: Bot, hours: int, flag: str) -> None:
    now = tz_now()
    until = now + timedelta(hours=hours)
    # Окна не пересекаются: за 24 ч напоминаем только о визитах,
    # до которых осталось больше 2 ч, иначе напоминание за 2 ч.
    conditions = [
        Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at <= until,
        getattr(Booking, flag).is_(False),
    ]
    if hours > 2:
        conditions.append(Booking.start_at > now + timedelta(hours=2))
    else:
        # Включаем ровно текущий момент, чтобы запись на границе окон
        # не осталась без напоминания.
        conditions.append(Booking.start_at >= now)

    async with SessionLocal() as session:
        bookings = list(
            await session.scalars(
                select(Booking)
                .options(selectinload(Booking.items), selectinload(Booking.client))
                .where(*conditions)
                .order_by(Booking.start_at)
            )
        )

    sent_ids: list[int] = []
    for booking in bookings:
        if booking.client is None:
            continue
        sent = await safe_send(
            bot,
            booking.client.tg_id,
            _reminder_text(booking, hours),
            _reminder_markup(booking),
        )
        if not sent:
            continue
        sent_ids.append(booking.id)
        logger.info("Напоминание за %s ч по записи №%s отправлено", hours, booking.id)

    if sent_ids:
        async with SessionLocal() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id.in_(sent_ids))
                .values({flag: True})
            )
            await session.commit()


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(
        expire_drafts_job,
        "interval",
        minutes=5,
        id="expire_drafts",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_reminders_job,
        "interval",
        minutes=30,
        args=(bot, 24, "reminder_24h_sent"),
        id="reminders_24h",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_reminders_job,
        "interval",
        minutes=15,
        args=(bot, 2, "reminder_2h_sent"),
        id="reminders_2h",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
