from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    Booking,
    BookingItem,
    BookingStatus,
    PriceMode,
    Service,
)
from app.services.availability import (
    is_range_available,
    required_minutes_for_booking,
    required_minutes_for_services,
)
from app.utils.timeutil import fmt_duration, tz_now

# Один процесс бота = одна очередь записи. Этого достаточно для SQLite,
# чтобы два клиента не получили один и тот же слот одновременно.
_booking_lock = asyncio.Lock()


class BookingError(Exception):
    """Ошибка бизнес-правила с текстом для пользователя."""


def is_draft_expired(booking: Booking, now: datetime | None = None) -> bool:
    if booking.status != BookingStatus.DRAFT:
        return False
    if booking.hold_expires_at is None:
        return True
    return booking.hold_expires_at <= (now or tz_now())


def _recalculate(booking: Booking) -> None:
    """Раскладывает услуги подряд от начала записи и пересчитывает итоги."""
    items = sorted(booking.items, key=lambda item: item.sort_order)
    cursor = booking.start_at
    total_minutes = 0
    total_price = 0
    is_estimate = False
    buffers: list[int] = []
    for index, item in enumerate(items):
        item.sort_order = index
        item.start_at = cursor
        item.end_at = cursor + timedelta(minutes=item.duration_minutes)
        cursor = item.end_at
        total_minutes += item.duration_minutes
        total_price += item.price or 0
        is_estimate = is_estimate or item.price_mode != PriceMode.FIXED
        buffers.append(item.buffer_minutes)
    booking.total_minutes = total_minutes
    booking.total_price = total_price
    booking.price_is_estimate = is_estimate
    booking.end_at = cursor + timedelta(minutes=max(buffers, default=0))


def _make_item(service: Service, sort_order: int, start_at: datetime) -> BookingItem:
    return BookingItem(
        service_id=service.id,
        title=service.title,
        price=service.price or 0,
        price_mode=service.price_mode,
        duration_minutes=service.duration_minutes,
        buffer_minutes=service.buffer_minutes,
        start_at=start_at,
        end_at=start_at,
        sort_order=sort_order,
    )


async def load_booking(session: AsyncSession, booking_id: int) -> Booking | None:
    return await session.scalar(
        select(Booking)
        .options(selectinload(Booking.items), selectinload(Booking.client))
        .where(Booking.id == booking_id)
        .execution_options(populate_existing=True)
    )


async def get_active_draft(
    session: AsyncSession, client_id: int, now: datetime | None = None
) -> Booking | None:
    now = now or tz_now()
    return await session.scalar(
        select(Booking)
        .options(selectinload(Booking.items))
        .where(
            Booking.client_id == client_id,
            Booking.status == BookingStatus.DRAFT,
            Booking.hold_expires_at > now,
        )
        .order_by(Booking.created_at.desc(), Booking.id.desc())
        .limit(1)
    )


async def expire_stale_drafts(session: AsyncSession, now: datetime | None = None) -> int:
    now = now or tz_now()
    result = await session.execute(
        update(Booking)
        .where(
            Booking.status == BookingStatus.DRAFT,
            or_(Booking.hold_expires_at.is_(None), Booking.hold_expires_at <= now),
        )
        .values(
            status=BookingStatus.CANCELLED,
            cancelled_at=now,
            cancel_reason="hold_expired",
            hold_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return result.rowcount or 0


async def create_draft(
    session: AsyncSession,
    *,
    client_id: int,
    services: Sequence[Service],
    start_at: datetime,
    now: datetime | None = None,
) -> Booking:
    services = list(services)
    if not services:
        raise BookingError("Выберите хотя бы одну услугу")
    seen: set[int] = set()
    for service in services:
        if not service.is_active:
            raise BookingError(f"Услуга «{service.title}» больше недоступна")
        if service.id in seen:
            raise BookingError("Эта услуга уже добавлена в запись")
        seen.add(service.id)

    required = required_minutes_for_services(services)
    now = now or tz_now()

    async with _booking_lock:
        await expire_stale_drafts(session, now)
        if not await is_range_available(
            session, start_at, required, now=now
        ):
            raise BookingError(
                "Это время уже занято. Пожалуйста, выберите другой слот."
            )

        booking = Booking(
            client_id=client_id,
            status=BookingStatus.DRAFT,
            start_at=start_at,
            end_at=start_at,
            hold_expires_at=now + timedelta(minutes=settings.hold_minutes),
            client_name="",
            client_phone="",
            source="telegram",
        )
        for index, service in enumerate(services):
            booking.items.append(_make_item(service, index, start_at))
        _recalculate(booking)
        session.add(booking)
        await session.commit()
        return await load_booking(session, booking.id) or booking


async def append_service(
    session: AsyncSession,
    booking_id: int,
    service: Service,
    *,
    now: datetime | None = None,
) -> Booking:
    now = now or tz_now()
    async with _booking_lock:
        booking = await load_booking(session, booking_id)
        if booking is None:
            raise BookingError("Запись не найдена")
        if booking.status != BookingStatus.DRAFT:
            raise BookingError("Эта запись уже оформлена")
        if is_draft_expired(booking, now):
            await clear_draft(session, booking_id, reason="hold_expired")
            raise BookingError(
                "Время удержания истекло, слот освобождён. Начните запись заново."
            )
        if not service.is_active:
            raise BookingError(f"Услуга «{service.title}» больше недоступна")
        if any(item.service_id == service.id for item in booking.items):
            raise BookingError("Эта услуга уже добавлена в запись")

        durations = sum(item.duration_minutes for item in booking.items)
        durations += service.duration_minutes
        buffer = max(
            [item.buffer_minutes for item in booking.items] + [service.buffer_minutes]
        )
        required = durations + buffer

        if not await is_range_available(
            session,
            booking.start_at,
            required,
            now=now,
            exclude_booking_id=booking.id,
        ):
            raise BookingError(
                f"Чтобы добавить «{service.title}», нужно "
                f"{fmt_duration(durations)} подряд — в это время не помещается. "
                "Выберите другое время или оформите запись с меньшим набором услуг."
            )

        booking.items.append(_make_item(service, len(booking.items), booking.start_at))
        _recalculate(booking)
        booking.hold_expires_at = now + timedelta(minutes=settings.hold_minutes)
        await session.commit()
        return await load_booking(session, booking.id) or booking


async def clear_draft(
    session: AsyncSession,
    booking_id: int,
    *,
    reason: str = "client_cleared",
    now: datetime | None = None,
) -> None:
    booking = await load_booking(session, booking_id)
    if booking is None or booking.status != BookingStatus.DRAFT:
        return
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now or tz_now()
    booking.cancel_reason = reason[:200]
    booking.hold_expires_at = None
    await session.commit()


async def confirm_booking(
    session: AsyncSession,
    booking_id: int,
    *,
    client_name: str,
    client_phone: str,
    comment: str = "",
    now: datetime | None = None,
) -> Booking:
    now = now or tz_now()
    if not client_name.strip():
        raise BookingError("Укажите имя")
    if not client_phone.strip():
        raise BookingError("Укажите телефон")

    async with _booking_lock:
        booking = await load_booking(session, booking_id)
        if booking is None:
            raise BookingError("Запись не найдена")
        if booking.status != BookingStatus.DRAFT:
            raise BookingError("Эта запись уже оформлена")
        if is_draft_expired(booking, now):
            await clear_draft(session, booking_id, reason="hold_expired", now=now)
            raise BookingError(
                "Время удержания истекло, слот освобождён. Начните запись заново."
            )
        required = required_minutes_for_booking(booking)
        if not await is_range_available(
            session,
            booking.start_at,
            required,
            now=now,
            exclude_booking_id=booking.id,
        ):
            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = now
            booking.cancel_reason = "slot_taken"
            booking.hold_expires_at = None
            await session.commit()
            raise BookingError(
                "Слот только что заняли. Выберите, пожалуйста, другое время."
            )

        booking.status = BookingStatus.CONFIRMED
        booking.hold_expires_at = None
        booking.client_name = client_name.strip()[:128]
        booking.client_phone = client_phone.strip()[:32]
        booking.comment = comment.strip()[:500]
        booking.reminder_24h_sent = False
        booking.reminder_2h_sent = False
        booking.client_confirmed = False
        await session.commit()
        return await load_booking(session, booking.id) or booking


def _client_change_allowed(booking: Booking, now: datetime) -> bool:
    return booking.start_at - now >= timedelta(hours=settings.cancel_cutoff_hours)


async def cancel_booking(
    session: AsyncSession,
    booking_id: int,
    *,
    reason: str = "",
    by_client: bool = True,
    now: datetime | None = None,
) -> Booking:
    now = now or tz_now()
    async with _booking_lock:
        booking = await load_booking(session, booking_id)
        if booking is None:
            raise BookingError("Запись не найдена")
        if booking.status not in (BookingStatus.DRAFT, BookingStatus.CONFIRMED):
            raise BookingError("Эту запись уже нельзя отменить")
        if (
            by_client
            and booking.status == BookingStatus.CONFIRMED
            and not _client_change_allowed(booking, now)
        ):
            raise BookingError(
                "До записи меньше "
                f"{settings.cancel_cutoff_hours} ч — отмена через бота недоступна. "
                "Пожалуйста, свяжитесь со студией."
            )
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = now
        booking.cancel_reason = (reason.strip() or "client_cancelled")[:200]
        booking.hold_expires_at = None
        await session.commit()
        return await load_booking(session, booking.id) or booking


async def reschedule_booking(
    session: AsyncSession,
    booking_id: int,
    new_start: datetime,
    *,
    by_client: bool = True,
    now: datetime | None = None,
) -> Booking:
    now = now or tz_now()
    async with _booking_lock:
        booking = await load_booking(session, booking_id)
        if booking is None:
            raise BookingError("Запись не найдена")
        if booking.status not in (BookingStatus.DRAFT, BookingStatus.CONFIRMED):
            raise BookingError("Эту запись уже нельзя перенести")
        if is_draft_expired(booking, now):
            await clear_draft(session, booking.id, reason="hold_expired", now=now)
            raise BookingError("Время удержания истекло. Начните запись заново.")
        if (
            by_client
            and booking.status == BookingStatus.CONFIRMED
            and not _client_change_allowed(booking, now)
        ):
            raise BookingError(
                "До записи меньше "
                f"{settings.cancel_cutoff_hours} ч — перенос через бота недоступен. "
                "Пожалуйста, свяжитесь со студией."
            )

        required = required_minutes_for_booking(booking)
        if not await is_range_available(
            session,
            new_start,
            required,
            now=now,
            exclude_booking_id=booking.id,
        ):
            raise BookingError("Это время уже занято. Выберите другой слот.")

        booking.start_at = new_start
        _recalculate(booking)
        booking.reminder_24h_sent = False
        booking.reminder_2h_sent = False
        booking.client_confirmed = False
        booking.hold_expires_at = (
            now + timedelta(minutes=settings.hold_minutes)
            if booking.status == BookingStatus.DRAFT
            else None
        )
        await session.commit()
        return await load_booking(session, booking.id) or booking


async def mark_status(
    session: AsyncSession,
    booking_id: int,
    status: BookingStatus,
) -> Booking:
    if status not in (BookingStatus.COMPLETED, BookingStatus.NO_SHOW):
        raise ValueError("Допустимы только completed и no_show")
    async with _booking_lock:
        booking = await load_booking(session, booking_id)
        if booking is None:
            raise BookingError("Запись не найдена")
        if booking.status not in (
            BookingStatus.CONFIRMED,
            BookingStatus.COMPLETED,
            BookingStatus.NO_SHOW,
        ):
            raise BookingError("Статус этой записи изменить нельзя")
        booking.status = status
        booking.hold_expires_at = None
        await session.commit()
        return await load_booking(session, booking.id) or booking


async def mark_client_confirmed(
    session: AsyncSession, booking_id: int, *, now: datetime | None = None
) -> bool:
    now = now or tz_now()
    booking = await load_booking(session, booking_id)
    if booking is None or booking.status != BookingStatus.CONFIRMED:
        return False
    if booking.start_at < now:
        return False
    booking.client_confirmed = True
    await session.commit()
    return True



