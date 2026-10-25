from __future__ import annotations

from datetime import date, datetime, timedelta

from app.config import settings

WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKDAYS_FULL = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
MONTHS_SHORT = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def tz_now() -> datetime:
    """Текущее время студии как naive datetime (единое время для всей БД)."""
    return datetime.now(settings.tz).replace(tzinfo=None)


def today() -> date:
    return tz_now().date()


def fmt_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def fmt_date_short(value: date) -> str:
    return f"{WEEKDAYS_SHORT[value.weekday()]}, {value.strftime('%d.%m')}"


def fmt_date_long(value: date) -> str:
    return f"{WEEKDAYS_FULL[value.weekday()]}, {value.day} {MONTHS_GENITIVE[value.month - 1]}"


def fmt_date_tiny(value: date) -> str:
    return value.strftime("%d.%m")


def fmt_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def fmt_interval(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
    return f"{start.strftime('%d.%m %H:%M')}–{end.strftime('%d.%m %H:%M')}"


def fmt_duration(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} ч {rest} мин"
    if hours:
        return f"{hours} ч"
    return f"{rest} мин"


def combine(day: date, minutes_from_midnight: int) -> datetime:
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=minutes_from_midnight)


def ceil_to_step(minutes: float, step: int) -> int:
    step = max(1, step)
    return int(-(-int(minutes) // step) * step)


def hhmm_to_minutes(value: str) -> int | None:
    """'10:30' -> 630. Возвращает None для некорректного значения."""
    try:
        hours_raw, minutes_raw = value.strip().split(":")
        hours, minutes = int(hours_raw), int(minutes_raw)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None
    return hours * 60 + minutes


def minutes_to_hhmm(minutes: int) -> str:
    minutes = max(0, min(24 * 60 - 1, int(minutes)))
    hours, rest = divmod(minutes, 60)
    return f"{hours:02d}:{rest:02d}"


def date_range(start: date, days: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(max(0, days))]
