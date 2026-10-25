from __future__ import annotations

import re

from app.db.models import PriceMode

_PRICE_MAX = 1_000_000
_DURATION_MAX = 600


def parse_price(raw: str) -> tuple[PriceMode, int | None, str | None]:
    """Разбирает ввод цены.

    10000 / 10 000 ₽      -> fixed 10000
    от 10000              -> from 10000
    от 1000 (за зону)     -> from 1000
    2500 + 300 за см²     -> custom, текст сохраняется как примечание
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("Введите цену или текстовое примечание")

    normalized = re.sub(r"(?i)\b(руб\.?|р\.|₽)\b", " ", text)
    normalized = normalized.replace("₽", " ").strip()
    digits = re.sub(r"\D", "", normalized)

    if normalized.lower().startswith("от"):
        if not digits:
            raise ValueError("После «от» нужна сумма, например: от 10000")
        value = int(digits)
        if value <= 0 or value > _PRICE_MAX:
            raise ValueError("Сумма должна быть больше 0 и меньше 1 000 000")
        return PriceMode.FROM, value, None

    if re.fullmatch(r"[\d\s]+", normalized or "x") and digits:
        value = int(digits)
        if value <= 0 or value > _PRICE_MAX:
            raise ValueError("Сумма должна быть больше 0 и меньше 1 000 000")
        return PriceMode.FIXED, value, None

    if len(text) > 200:
        raise ValueError("Примечание к цене слишком длинное (максимум 200 символов)")
    return PriceMode.CUSTOM, None, text


def parse_duration(raw: str) -> int:
    """'90', '1ч30', '1 час 30 мин', '45 минут' -> минуты."""
    text = (raw or "").strip().lower().replace("ё", "е")
    if not text:
        raise ValueError("Введите длительность в минутах")

    if text.isdigit():
        minutes = int(text)
    else:
        hours_match = re.search(r"(\d+)\s*(?:ч|час)", text)
        minutes_match = re.search(r"(\d+)\s*(?:м|мин)", text)
        if not hours_match and not minutes_match:
            raise ValueError("Не понял длительность. Примеры: 60, 1ч30, 90 мин")
        minutes = int(hours_match.group(1)) * 60 if hours_match else 0
        minutes += int(minutes_match.group(1)) if minutes_match else 0

    if minutes < 5 or minutes > _DURATION_MAX:
        raise ValueError("Длительность должна быть от 5 до 600 минут")
    return minutes


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits

    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    if 11 <= len(digits) <= 15:
        return "+" + digits
    return None


def parse_comment(raw: str, limit: int = 500) -> str:
    text = (raw or "").strip()
    if len(text) > limit:
        raise ValueError(f"Комментарий слишком длинный (максимум {limit} символов)")
    return text


def parse_windows(raw: str) -> list[tuple[int, int]]:
    """'10:00-14:00, 15:00-20:00' -> [(600, 840), (900, 1200)]."""
    from app.utils.timeutil import hhmm_to_minutes

    text = (raw or "").strip().lower().replace("–", "-").replace("—", "-")
    if not text:
        raise ValueError("Введите окна, например: 10:00-14:00, 15:00-20:00")
    chunks = [chunk.strip() for chunk in text.split(",") if chunk.strip()]
    if not chunks:
        raise ValueError("Введите хотя бы одно окно")

    windows: list[tuple[int, int]] = []
    for chunk in chunks:
        parts = chunk.split("-")
        if len(parts) != 2:
            raise ValueError("Формат окна: 10:00-14:00")
        start = hhmm_to_minutes(parts[0])
        end = hhmm_to_minutes(parts[1])
        if start is None or end is None:
            raise ValueError("Неверное время. Формат: 10:00-14:00")
        if end - start < 30:
            raise ValueError("Окно должно быть не короче 30 минут")
        windows.append((start, end))

    windows.sort()
    for previous, current in zip(windows, windows[1:]):
        if current[0] < previous[1]:
            raise ValueError("Окна не должны пересекаться")
    return windows

