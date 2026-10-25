from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    Booking,
    BookingStatus,
    ScheduleDay,
    ScheduleStatus,
    WeekdayTemplate,
    WorkingWindow,
)
from app.db.seed import DEFAULT_TEMPLATE
from app.services.availability import merge_windows
from app.utils.timeutil import date_range, minutes_to_hhmm, tz_now, today

PRESETS: dict[str, tuple[str, list[tuple[int, int]]]] = {
    "full": ("10:00–20:00", [(10 * 60, 20 * 60)]),
    "short": ("10:00–16:00", [(10 * 60, 16 * 60)]),
    "evening": ("14:00–20:00", [(14 * 60, 20 * 60)]),
    "split": ("10:00–14:00 и 15:00–20:00", [(600, 840), (900, 1200)]),
    "late": ("12:00–21:00", [(12 * 60, 21 * 60)]),
}

MIN_WINDOW_MINUTES = 30
DEFAULT_WINDOW_START = 10 * 60
DEFAULT_WINDOW_END = 14 * 60


@dataclass
class DayInfo:
    date: date
    status: ScheduleStatus
    windows: list[tuple[int, int]] = field(default_factory=list)
    bookings: int = 0
    revenue: int = 0
    note: str = ""

    @property
    def is_open(self) -> bool:
        return bool(self.windows) and self.status != ScheduleStatus.CLOSED

    @property
    def windows_text(self) -> str:
        if not self.windows:
            return "—"
        return ", ".join(
            f"{minutes_to_hhmm(start)}–{minutes_to_hhmm(end)}" for start, end in self.windows
        )

    @property
    def total_hours(self) -> float:
        return sum(end - start for start, end in self.windows) / 60


@dataclass
class ScheduleIssue:
    date: date
    status: ScheduleStatus
    bookings: int


def normalize_template_windows(raw: Iterable) -> list[tuple[int, int]]:
    """Приводит JSON-шаблон (dict/tuple) к валидным минутам."""
    windows: list[tuple[int, int]] = []
    for item in raw or []:
        if isinstance(item, dict):
            start_raw, end_raw = item.get("start"), item.get("end")
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            start_raw, end_raw = item
        else:
            continue
        try:
            start, end = int(start_raw), int(end_raw)
        except (TypeError, ValueError):
            continue
        start = max(0, min(24 * 60, start))
        end = max(0, min(24 * 60, end))
        if end - start >= MIN_WINDOW_MINUTES:
            windows.append((start, end))
    return sorted(windows)


def windows_to_json(windows: Iterable[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"start": start, "end": end} for start, end in windows]


def apply_preset(day: ScheduleDay, preset_key: str) -> bool:
    preset = PRESETS.get(preset_key)
    if preset is None:
        return False
    _, windows = preset
    replace_windows(day, windows)
    return True


def replace_windows(day: ScheduleDay, windows: Iterable[tuple[int, int]]) -> None:
    normalized = merge_windows(windows)
    day.windows.clear()
    for start, end in normalized:
        day.windows.append(WorkingWindow(start_minute=start, end_minute=end))
    day.updated_at = tz_now()


async def templates_map(session: AsyncSession) -> dict[int, WeekdayTemplate]:
    result = {
        template.weekday: template
        for template in await session.scalars(
            select(WeekdayTemplate).order_by(WeekdayTemplate.weekday)
        )
    }
    created = False
    for weekday in range(7):
        if weekday in result:
            continue
        windows = normalize_template_windows(DEFAULT_TEMPLATE.get(weekday, []))
        template = WeekdayTemplate(
            weekday=weekday,
            is_working=bool(windows),
            windows=windows_to_json(windows),
        )
        session.add(template)
        result[weekday] = template
        created = True
    if created:
        await session.commit()
    return result


async def templates_list(session: AsyncSession) -> list[WeekdayTemplate]:
    mapping = await templates_map(session)
    return [mapping[weekday] for weekday in range(7)]


async def save_template(
    session: AsyncSession,
    weekday: int,
    windows: Iterable[tuple[int, int]],
) -> WeekdayTemplate:
    mapping = await templates_map(session)
    template = mapping[weekday]
    normalized = normalize_template_windows(list(windows))
    template.windows = windows_to_json(normalized)
    template.is_working = bool(normalized)
    await session.commit()
    return template


async def get_day(session: AsyncSession, day: date) -> ScheduleDay | None:
    return await session.scalar(
        select(ScheduleDay)
        .options(selectinload(ScheduleDay.windows))
        .where(ScheduleDay.date == day)
    )


def _template_windows(template: WeekdayTemplate | None) -> list[tuple[int, int]]:
    if template is None or not template.is_working:
        return []
    return normalize_template_windows(template.windows)


async def ensure_horizon(
    session: AsyncSession,
    start: date | None = None,
    days: int | None = None,
) -> int:
    """Создаёт недостающие дни горизонта из шаблона недели (черновиками)."""
    horizon_start = max(start or today(), today())
    horizon_days = days or settings.schedule_horizon_days
    dates = date_range(horizon_start, horizon_days)
    if not dates:
        return 0

    existing = set(
        await session.scalars(
            select(ScheduleDay.date).where(
                ScheduleDay.date >= dates[0], ScheduleDay.date <= dates[-1]
            )
        )
    )
    templates = await templates_map(session)
    created = 0
    for current in dates:
        if current in existing:
            continue
        windows = _template_windows(templates.get(current.weekday()))
        day = ScheduleDay(
            date=current,
            status=ScheduleStatus.DRAFT if windows else ScheduleStatus.CLOSED,
        )
        for window_start, window_end in windows:
            day.windows.append(
                WorkingWindow(start_minute=window_start, end_minute=window_end)
            )
        session.add(day)
        created += 1
    if created:
        await session.commit()
    return created


async def get_or_create_day(session: AsyncSession, day_date: date) -> ScheduleDay:
    day = await get_day(session, day_date)
    if day is not None:
        return day
    templates = await templates_map(session)
    windows = _template_windows(templates.get(day_date.weekday()))
    day = ScheduleDay(date=day_date, status=ScheduleStatus.DRAFT)
    for window_start, window_end in windows:
        day.windows.append(WorkingWindow(start_minute=window_start, end_minute=window_end))
    session.add(day)
    await session.commit()
    return await get_day(session, day_date) or day


async def _booking_stats(
    session: AsyncSession, start: date, days: int
) -> dict[date, tuple[int, int]]:
    range_start = datetime.combine(start, time.min)
    range_end = datetime.combine(start + timedelta(days=days), time.min)
    rows = await session.execute(
        select(Booking.start_at, Booking.total_price).where(
            Booking.start_at >= range_start,
            Booking.start_at < range_end,
            Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.COMPLETED)),
        )
    )
    stats: dict[date, tuple[int, int]] = {}
    for start_at, price in rows:
        count, revenue = stats.get(start_at.date(), (0, 0))
        stats[start_at.date()] = (count + 1, revenue + (price or 0))
    return stats


async def overview(
    session: AsyncSession, start: date, days: int | None = None
) -> list[DayInfo]:
    days = days or settings.schedule_horizon_days
    schedule_days = list(
        await session.scalars(
            select(ScheduleDay)
            .options(selectinload(ScheduleDay.windows))
            .where(
                ScheduleDay.date >= start,
                ScheduleDay.date < start + timedelta(days=days),
            )
            .order_by(ScheduleDay.date)
        )
    )
    stats = await _booking_stats(session, start, days)
    result: list[DayInfo] = []
    for day in schedule_days:
        bookings, revenue = stats.get(day.date, (0, 0))
        result.append(
            DayInfo(
                date=day.date,
                status=day.status,
                windows=merge_windows(day.effective_windows()),
                bookings=bookings,
                revenue=revenue,
                note=day.note or "",
            )
        )
    return result


async def day_info(session: AsyncSession, day_date: date) -> DayInfo:
    day = await get_day(session, day_date)
    stats = await _booking_stats(session, day_date, 1)
    bookings, revenue = stats.get(day_date, (0, 0))
    if day is None:
        return DayInfo(date=day_date, status=ScheduleStatus.DRAFT, bookings=bookings, revenue=revenue)
    return DayInfo(
        date=day.date,
        status=day.status,
        windows=merge_windows(day.effective_windows()),
        bookings=bookings,
        revenue=revenue,
        note=day.note or "",
    )


async def upcoming_issues(session: AsyncSession, days: int = 14) -> list[ScheduleIssue]:
    """Черновики в ближайшие дни — их нужно заполнить и опубликовать."""
    start = today()
    stats = await _booking_stats(session, start, days)
    rows = await session.scalars(
        select(ScheduleDay)
        .where(
            ScheduleDay.date >= start,
            ScheduleDay.date < start + timedelta(days=days),
            ScheduleDay.status == ScheduleStatus.DRAFT,
        )
        .order_by(ScheduleDay.date)
    )
    return [
        ScheduleIssue(
            date=day.date,
            status=day.status,
            bookings=stats.get(day.date, (0, 0))[0],
        )
        for day in rows
    ]


def _sorted_windows(day: ScheduleDay) -> list[WorkingWindow]:
    return sorted(day.windows, key=lambda window: window.start_minute)


async def add_window(session: AsyncSession, day_date: date) -> bool:
    day = await get_or_create_day(session, day_date)
    windows = _sorted_windows(day)
    if not windows:
        start, end = DEFAULT_WINDOW_START, DEFAULT_WINDOW_END
    else:
        last_end = max(window.end_minute for window in windows)
        start = last_end + 60
        end = min(start + 120, 23 * 60)
        if start >= 22 * 60 or end - start < MIN_WINDOW_MINUTES:
            return False
    day.windows.append(WorkingWindow(start_minute=start, end_minute=end))
    day.updated_at = tz_now()
    await session.commit()
    return True


async def shift_window(
    session: AsyncSession,
    day_date: date,
    index: int,
    edge: str,
    delta: int,
) -> bool:
    """Сдвигает начало/конец окна, не давая ему налезть на соседнее."""
    day = await get_or_create_day(session, day_date)
    windows = _sorted_windows(day)
    if not (0 <= index < len(windows)) or edge not in {"start", "end"}:
        return False

    window = windows[index]
    if edge == "start":
        lower = windows[index - 1].end_minute if index > 0 else 0
        upper = window.end_minute - MIN_WINDOW_MINUTES
        if index + 1 < len(windows):
            upper = min(upper, windows[index + 1].start_minute - MIN_WINDOW_MINUTES)
        new_value = max(lower, min(window.start_minute + delta, upper))
        if new_value == window.start_minute:
            return False
        window.start_minute = new_value
    else:
        lower = window.start_minute + MIN_WINDOW_MINUTES
        if index > 0:
            lower = max(lower, windows[index - 1].end_minute + MIN_WINDOW_MINUTES)
        upper = windows[index + 1].start_minute if index + 1 < len(windows) else 24 * 60
        new_value = min(upper, max(window.end_minute + delta, lower))
        if new_value == window.end_minute:
            return False
        window.end_minute = new_value

    day.updated_at = tz_now()
    await session.commit()
    return True


async def delete_window(session: AsyncSession, day_date: date, index: int) -> bool:
    day = await get_or_create_day(session, day_date)
    windows = _sorted_windows(day)
    if not (0 <= index < len(windows)):
        return False
    await session.delete(windows[index])
    day.updated_at = tz_now()
    await session.commit()
    return True


async def apply_template_to_day(session: AsyncSession, day_date: date) -> bool:
    day = await get_or_create_day(session, day_date)
    templates = await templates_map(session)
    windows = _template_windows(templates.get(day_date.weekday()))
    replace_windows(day, windows)
    if not windows:
        day.status = ScheduleStatus.CLOSED
    await session.commit()
    return bool(windows)


async def publish_day(session: AsyncSession, day_date: date) -> bool:
    day = await get_or_create_day(session, day_date)
    if not merge_windows(day.effective_windows()):
        return False
    day.status = ScheduleStatus.PUBLISHED
    day.updated_at = tz_now()
    await session.commit()
    return True


async def close_day(session: AsyncSession, day_date: date) -> bool:
    day = await get_or_create_day(session, day_date)
    day.status = ScheduleStatus.CLOSED
    day.updated_at = tz_now()
    await session.commit()
    return True


async def copy_day(session: AsyncSession, target_date: date, source_date: date) -> bool:
    source = await get_day(session, source_date)
    if source is None:
        return False
    target = await get_or_create_day(session, target_date)
    source_windows = merge_windows(source.effective_windows())
    replace_windows(target, source_windows)
    target.note = source.note or ""
    if not source_windows:
        target.status = ScheduleStatus.CLOSED
    elif target.status != ScheduleStatus.PUBLISHED:
        target.status = ScheduleStatus.DRAFT
    await session.commit()
    return True


async def copy_previous_day(session: AsyncSession, day_date: date) -> bool:
    return await copy_day(session, day_date, day_date - timedelta(days=1))


async def copy_week(session: AsyncSession, anchor: date) -> tuple[int, list[date]]:
    """Копирует расписание с прошлой недели на ту же неделю, что и anchor."""
    monday = anchor - timedelta(days=anchor.weekday())
    copied = 0
    conflicts: list[date] = []
    for offset in range(7):
        target_date = monday + timedelta(days=offset)
        if target_date < today():
            continue
        source_date = target_date - timedelta(days=7)
        source = await get_day(session, source_date)
        if source is None:
            continue
        target = await get_or_create_day(session, target_date)
        stats = await _booking_stats(session, target_date, 1)
        if stats.get(target_date, (0, 0))[0]:
            conflicts.append(target_date)
        source_windows = merge_windows(source.effective_windows())
        replace_windows(target, source_windows)
        target.note = source.note or ""
        if not source_windows:
            target.status = ScheduleStatus.CLOSED
        elif target.status != ScheduleStatus.PUBLISHED:
            target.status = ScheduleStatus.DRAFT
        await session.commit()
        copied += 1
    return copied, conflicts


async def publish_week(session: AsyncSession, anchor: date) -> int:
    monday = anchor - timedelta(days=anchor.weekday())
    published = 0
    for offset in range(7):
        target_date = monday + timedelta(days=offset)
        if target_date < today():
            continue
        day = await get_day(session, target_date)
        if day is None or not merge_windows(day.effective_windows()):
            continue
        day.status = ScheduleStatus.PUBLISHED
        day.updated_at = tz_now()
        published += 1
    if published:
        await session.commit()
    return published


async def publish_drafts(session: AsyncSession) -> tuple[int, int]:
    """Заполняет пустые черновики по шаблону и публикует их.

    Уже настроенные вручную окна черновиков сохраняются как есть.
    """
    start = today()
    drafts = list(
        await session.scalars(
            select(ScheduleDay)
            .options(selectinload(ScheduleDay.windows))
            .where(
                ScheduleDay.date >= start,
                ScheduleDay.date < start + timedelta(days=settings.schedule_horizon_days),
                ScheduleDay.status == ScheduleStatus.DRAFT,
            )
        )
    )
    templates = await templates_map(session)
    published = 0
    closed = 0
    for day in drafts:
        if not merge_windows(day.effective_windows()):
            replace_windows(day, _template_windows(templates.get(day.date.weekday())))
        if merge_windows(day.effective_windows()):
            day.status = ScheduleStatus.PUBLISHED
            published += 1
        else:
            day.status = ScheduleStatus.CLOSED
            closed += 1
    if drafts:
        await session.commit()
    return published, closed




