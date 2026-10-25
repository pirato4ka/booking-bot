from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

COOKIE_NAME = "studio_admin"
SESSION_TTL_SECONDS = 12 * 60 * 60


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _safe_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass
class AdminAuth:
    """Подписанная cookie-сессия без серверного хранилища.

    Пароль задаётся в ADMIN_PANEL_PASSWORD, секрет подписи — в
    ADMIN_PANEL_SECRET. Панель рассчитана на работу за HTTPS.
    """

    username: str
    password: str
    secret: str
    ttl_seconds: int = SESSION_TTL_SECONDS
    secure_cookie: bool = False

    @property
    def cookie_name(self) -> str:
        return COOKIE_NAME

    def verify_credentials(self, username: str, password: str) -> bool:
        user_ok = _safe_equals((username or "").strip(), self.username)
        password_ok = _safe_equals(password or "", self.password)
        return user_ok and password_ok

    def _signature(self, payload: str) -> str:
        return hmac.new(
            self.secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
        ).hexdigest()

    def create_session(self) -> tuple[str, dict[str, Any]]:
        now = int(time.time())
        session = {
            "sub": self.username,
            "csrf": secrets.token_urlsafe(24),
            "iat": now,
            "exp": now + self.ttl_seconds,
        }
        payload = _b64encode(json.dumps(session, separators=(",", ":")).encode("utf-8"))
        return f"{payload}.{self._signature(payload)}", session

    def read_session(self, token: str | None) -> dict[str, Any] | None:
        if not token or token.count(".") != 1:
            return None
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, self._signature(payload)):
            return None
        try:
            session = json.loads(_b64decode(payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(session, dict):
            return None
        if session.get("sub") != self.username:
            return None
        if int(session.get("exp", 0)) <= int(time.time()):
            return None
        return session

    def check_csrf(self, session: dict[str, Any] | None, token: str | None) -> bool:
        if not session or not token:
            return False
        return _safe_equals(str(session.get("csrf", "")), token)


@dataclass
class LoginThrottle:
    """Простое ограничение попыток входа по IP."""

    limit: int = 8
    window_seconds: int = 600
    _attempts: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def _prune(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return attempts

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic())) >= self.limit

    def register_failure(self, key: str) -> None:
        self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
