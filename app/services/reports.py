from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Booking, BookingStatus, ScheduleDay, User
from app.utils.timeutil import tz_now

ACTIVE_STATUSES = (
    BookingStatus.CONFIRMED,
    BookingStatus.COMPLETED,
    BookingStatus.NO_SHOW,
)


async def client_future_bookings(
    session: AsyncSession, client_id: int, *, now: datetime | None = None
) -> list[Booking]:
    now = now or tz_now()
    result = await session.scalars(
        select(Booking)
        .options(selectinload(Booking.items))
        .where(
            Booking.client_id == client_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at >= now - timedelta(hours=2),
        )
        .order_by(Booking.start_at)
    )
    return list(result)


async def client_past_bookings(
    session: AsyncSession, client_id: int, *, limit: int = 10
) -> list[Booking]:
    result = await session.scalars(
        select(Booking)
        .options(selectinload(Booking.items))
        .where(
            Booking.client_id == client_id,
            Booking.status.in_(
                (BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.NO_SHOW)
            ),
        )
        .order_by(Booking.start_at.desc())
        .limit(limit)
    )
    return list(result)


async def client_has_bookings(session: AsyncSession, client_id: int) -> bool:
    return (
        await session.scalar(
            select(Booking.id).where(Booking.client_id == client_id).limit(1)
        )
        is not None
    )


async def bookings_for_day(
    session: AsyncSession,
    day: date,
    *,
    now: datetime | None = None,
    include_cancelled: bool = False,
) -> list[Booking]:
    now = now or tz_now()
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    statement = select(Booking).options(selectinload(Booking.items)).where(
        Booking.start_at < day_end,
        Booking.end_at > day_start,
    )
    if not include_cancelled:
        statement = statement.where(
            Booking.status.in_((BookingStatus.DRAFT, *ACTIVE_STATUSES)),
            or_(Booking.status != BookingStatus.DRAFT, Booking.hold_expires_at > now),
        )
    statement = statement.order_by(Booking.start_at, Booking.id)
    return list(await session.scalars(statement))


async def upcoming_bookings(
    session: AsyncSession,
    *,
    days: int = 7,
    now: datetime | None = None,
) -> list[Booking]:
    now = now or tz_now()
    until = now + timedelta(days=max(1, days))
    result = await session.scalars(
        select(Booking)
        .options(selectinload(Booking.items))
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at >= now,
            Booking.start_at < until,
        )
        .order_by(Booking.start_at)
    )
    return list(result)


async def booking_neighbour_dates(
    session: AsyncSession, day: date, *, now: datetime | None = None
) -> tuple[date | None, date | None]:
    """Предыдущая и следующая даты с записями — для листания в админке."""
    now = now or tz_now()
    day_start = datetime.combine(day, time.min)
    previous = await session.scalar(
        select(func.max(Booking.start_at)).where(
            Booking.start_at < day_start, Booking.status.in_(ACTIVE_STATUSES)
        )
    )
    following = await session.scalar(
        select(func.min(Booking.start_at)).where(
            Booking.start_at >= day_start + timedelta(days=1),
            Booking.status.in_(ACTIVE_STATUSES),
        )
    )
    return (
        previous.date() if previous else None,
        following.date() if following else None,
    )


async def admin_stats(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or tz_now()
    today_start = datetime.combine(now.date(), time.min)
    tomorrow_start = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)
    month_start = datetime(now.year, now.month, 1)
    next_month = (
        datetime(now.year + 1, 1, 1)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1)
    )

    async def count(start: datetime, end: datetime) -> int:
        return int(
            await session.scalar(
                select(func.count(Booking.id)).where(
                    Booking.start_at >= start,
                    Booking.start_at < end,
                    Booking.status.in_(ACTIVE_STATUSES),
                )
            )
            or 0
        )

    month_revenue = await session.scalar(
        select(func.coalesce(func.sum(Booking.total_price), 0)).where(
            Booking.start_at >= month_start,
            Booking.start_at < next_month,
            Booking.status == BookingStatus.COMPLETED,
        )
    )
    new_clients = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= month_start)
    )
    holds = await session.scalar(
        select(func.count(Booking.id)).where(
            Booking.status == BookingStatus.DRAFT, Booking.hold_expires_at > now
        )
    )
    unpublished = await session.scalar(
        select(func.count(ScheduleDay.id)).where(
            ScheduleDay.date >= now.date(),
            ScheduleDay.date < now.date() + timedelta(days=14),
            ScheduleDay.status == "draft",
        )
    )
    return {
        "today": await count(today_start, tomorrow_start),
        "tomorrow": await count(tomorrow_start, tomorrow_start + timedelta(days=1)),
        "week": await count(today_start, week_end),
        "holds": int(holds or 0),
        "month_revenue": int(month_revenue or 0),
        "new_clients": int(new_clients or 0),
        "unpublished": int(unpublished or 0),
        "horizon": settings.schedule_horizon_days,
    }
