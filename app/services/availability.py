from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    Booking,
    BookingStatus,
    ScheduleDay,
    ScheduleStatus,
    Service,
)
from app.utils.timeutil import ceil_to_step, tz_now

BLOCKING_STATUSES = (
    BookingStatus.DRAFT,
    BookingStatus.CONFIRMED,
    BookingStatus.COMPLETED,
    BookingStatus.NO_SHOW,
)


@dataclass(frozen=True)
class DayAvailability:
    date: date
    slots: list[int]

    @property
    def first_slot(self) -> int:
        return self.slots[0]


def merge_windows(windows: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Сортирует и склеивает пересекающиеся/смежные окна."""
    normalized = sorted(
        (max(0, int(start)), min(24 * 60, int(end)))
        for start, end in windows
        if int(end) > int(start)
    )
    merged: list[tuple[int, int]] = []
    for start, end in normalized:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def build_slots(
    windows: Iterable[tuple[int, int]],
    busy: Iterable[tuple[int, int]],
    required_minutes: int,
    step_minutes: int,
    earliest_minute: int = 0,
) -> list[int]:
    """Чистый алгоритм свободных слотов (минуты от полуночи).

    Слот валиден, если весь интервал [start, start + required) помещается
    в рабочее окно и не пересекается ни с одной занятой записью.
    """
    if required_minutes <= 0:
        raise ValueError("required_minutes должен быть больше нуля")
    step = max(1, int(step_minutes))
    busy_list = list(busy)
    slots: list[int] = []
    for window_start, window_end in merge_windows(windows):
        start = max(window_start, int(earliest_minute))
        start = max(window_start, ceil_to_step(start, step))
        while start + required_minutes <= window_end:
            if not any(
                ranges_overlap(start, start + required_minutes, busy_start, busy_end)
                for busy_start, busy_end in busy_list
            ):
                slots.append(start)
            start += step
    return slots


def required_minutes_for_services(services: Iterable[Service]) -> int:
    items = list(services)
    if not items:
        return 0
    return sum(service.duration_minutes for service in items) + max(
        service.buffer_minutes for service in items
    )


def required_minutes_for_booking(booking: Booking) -> int:
    if not booking.items:
        return 0
    return sum(item.duration_minutes for item in booking.items) + max(
        item.buffer_minutes for item in booking.items
    )


async def get_schedule_day(session: AsyncSession, day: date) -> ScheduleDay | None:
    return await session.scalar(
        select(ScheduleDay)
        .options(selectinload(ScheduleDay.windows))
        .where(ScheduleDay.date == day)
    )


async def _busy_for_day(
    session: AsyncSession,
    day: date,
    *,
    now: datetime,
    exclude_booking_id: int | None = None,
) -> list[tuple[int, int]]:
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    statement = select(Booking).where(
        Booking.start_at < day_end,
        Booking.end_at > day_start,
        Booking.status.in_(BLOCKING_STATUSES),
        or_(Booking.status != BookingStatus.DRAFT, Booking.hold_expires_at > now),
    )
    if exclude_booking_id is not None:
        statement = statement.where(Booking.id != exclude_booking_id)

    intervals: list[tuple[int, int]] = []
    for booking in await session.scalars(statement):
        start = max(booking.start_at, day_start)
        end = min(booking.end_at, day_end)
        intervals.append(
            (
                int((start - day_start).total_seconds() // 60),
                int((end - day_start).total_seconds() // 60),
            )
        )
    return intervals


def _earliest_minute(day: date, now: datetime) -> int | None:
    """None — день уже недоступен, иначе минимальная минута старта."""
    cutoff = now + timedelta(minutes=settings.min_lead_minutes)
    if cutoff.date() > day:
        return None
    if cutoff.date() == day:
        return cutoff.hour * 60 + cutoff.minute + (1 if cutoff.second else 0)
    return 0


async def available_slots(
    session: AsyncSession,
    day: date,
    required_minutes: int,
    *,
    now: datetime | None = None,
    exclude_booking_id: int | None = None,
) -> list[int]:
    now = now or tz_now()
    if day < now.date() or required_minutes <= 0:
        return []

    schedule_day = await get_schedule_day(session, day)
    if schedule_day is None or schedule_day.status != ScheduleStatus.PUBLISHED:
        return []

    windows = merge_windows(schedule_day.effective_windows())
    if not windows:
        return []

    earliest = _earliest_minute(day, now)
    if earliest is None:
        return []

    busy = await _busy_for_day(
        session, day, now=now, exclude_booking_id=exclude_booking_id
    )
    return build_slots(
        windows,
        busy,
        required_minutes,
        settings.slot_step_minutes,
        earliest_minute=earliest,
    )


async def available_days(
    session: AsyncSession,
    required_minutes: int,
    start_day: date,
    days: int,
    *,
    now: datetime | None = None,
    exclude_booking_id: int | None = None,
) -> list[DayAvailability]:
    now = now or tz_now()
    if days <= 0 or required_minutes <= 0:
        return []

    end_day = start_day + timedelta(days=days)
    schedule_days = list(
        await session.scalars(
            select(ScheduleDay)
            .options(selectinload(ScheduleDay.windows))
            .where(
                ScheduleDay.date >= start_day,
                ScheduleDay.date < end_day,
                ScheduleDay.status == ScheduleStatus.PUBLISHED,
            )
            .order_by(ScheduleDay.date)
        )
    )
    if not schedule_days:
        return []

    range_start = datetime.combine(start_day, time.min)
    range_end = datetime.combine(end_day, time.min)
    statement = select(Booking).where(
        Booking.start_at < range_end,
        Booking.end_at > range_start,
        Booking.status.in_(BLOCKING_STATUSES),
        or_(Booking.status != BookingStatus.DRAFT, Booking.hold_expires_at > now),
    )
    if exclude_booking_id is not None:
        statement = statement.where(Booking.id != exclude_booking_id)

    busy_by_day: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for booking in await session.scalars(statement):
        current = max(booking.start_at.date(), start_day)
        last = min(booking.end_at.date(), end_day - timedelta(days=1))
        while current <= last:
            day_start = datetime.combine(current, time.min)
            day_end = day_start + timedelta(days=1)
            start = max(booking.start_at, day_start)
            end = min(booking.end_at, day_end)
            busy_by_day[current].append(
                (
                    int((start - day_start).total_seconds() // 60),
                    int((end - day_start).total_seconds() // 60),
                )
            )
            current += timedelta(days=1)

    result: list[DayAvailability] = []
    for schedule_day in schedule_days:
        earliest = _earliest_minute(schedule_day.date, now)
        if earliest is None:
            continue
        windows = merge_windows(schedule_day.effective_windows())
        if not windows:
            continue
        slots = build_slots(
            windows,
            busy_by_day.get(schedule_day.date, []),
            required_minutes,
            settings.slot_step_minutes,
            earliest_minute=earliest,
        )
        if slots:
            result.append(DayAvailability(date=schedule_day.date, slots=slots))
    return result


async def is_range_available(
    session: AsyncSession,
    start_at: datetime,
    required_minutes: int,
    *,
    now: datetime | None = None,
    exclude_booking_id: int | None = None,
    enforce_lead: bool = True,
) -> bool:
    now = now or tz_now()
    if required_minutes <= 0:
        return False
    end_at = start_at + timedelta(minutes=required_minutes)
    if start_at.date() != end_at.date():
        return False
    if start_at.date() < now.date():
        return False

    schedule_day = await get_schedule_day(session, start_at.date())
    if schedule_day is None or schedule_day.status != ScheduleStatus.PUBLISHED:
        return False

    start_minute = start_at.hour * 60 + start_at.minute
    end_minute = start_minute + required_minutes
    windows = merge_windows(schedule_day.effective_windows())
    if not any(
        window_start <= start_minute and end_minute <= window_end
        for window_start, window_end in windows
    ):
        return False

    if enforce_lead and start_at < now + timedelta(minutes=settings.min_lead_minutes):
        return False

    statement = select(Booking.id).where(
        Booking.start_at < end_at,
        Booking.end_at > start_at,
        Booking.status.in_(BLOCKING_STATUSES),
        or_(Booking.status != BookingStatus.DRAFT, Booking.hold_expires_at > now),
    )
    if exclude_booking_id is not None:
        statement = statement.where(Booking.id != exclude_booking_id)
    return await session.scalar(statement) is None



