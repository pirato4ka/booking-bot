from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, читаются из .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str = ""
    admin_ids: str = ""

    studio_name: str = "Адам и Ева"
    studio_tagline: str = "Студия красоты и эстетики тела"
    studio_address: str = ""
    studio_phone: str = ""
    studio_instagram: str = ""

    timezone: str = "Europe/Moscow"
    db_url: str = "sqlite+aiosqlite:///./data/bot.db"

    # Веб-панель администратора (python -m app.web)
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    admin_panel_user: str = "admin"
    admin_panel_password: str = ""
    admin_panel_secret: str = ""
    admin_cookie_secure: bool = False
    site_dir: str = "site"

    slot_step_minutes: int = 30
    min_lead_minutes: int = 120
    hold_minutes: int = 15
    cancel_cutoff_hours: int = 3
    schedule_horizon_days: int = 35

    log_level: str = "INFO"

    @field_validator("slot_step_minutes")
    @classmethod
    def _validate_step(cls, value: int) -> int:
        if value < 5 or value > 120:
            raise ValueError("SLOT_STEP_MINUTES должен быть от 5 до 120")
        return value

    @field_validator("schedule_horizon_days")
    @classmethod
    def _validate_horizon(cls, value: int) -> int:
        if value < 7 or value > 180:
            raise ValueError("SCHEDULE_HORIZON_DAYS должен быть от 7 до 180")
        return value

    @field_validator("web_port")
    @classmethod
    def _validate_web_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("WEB_PORT должен быть от 1 до 65535")
        return value

    @property
    def admin_id_set(self) -> set[int]:
        result: set[int] = set()
        for raw in self.admin_ids.replace(";", ",").split(","):
            raw = raw.strip()
            if raw.lstrip("-").isdigit():
                result.add(int(raw))
        return result

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def studio_contacts(self) -> str:
        parts: list[str] = []
        if self.studio_address:
            parts.append(f"📍 {self.studio_address}")
        if self.studio_phone:
            parts.append(f"📞 {self.studio_phone}")
        if self.studio_instagram:
            handle = self.studio_instagram.lstrip("@")
            parts.append(f"📸 https://instagram.com/{handle}")
        return "\n".join(parts)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
