from __future__ import annotations

import re

_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, fallback: str = "category") -> str:
    """«Холодная плазма» -> «holodnaya-plazma»."""
    translated = "".join(_TRANSLIT.get(char, char) for char in (value or "").lower())
    slug = _SLUG_RE.sub("-", translated).strip("-")
    return slug[:60].strip("-") or fallback


def is_valid_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value or ""))
