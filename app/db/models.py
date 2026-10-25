from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def enum_col(enum_cls: type[StrEnum], length: int = 24) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
        length=length,
        validate_strings=True,
    )


class PriceMode(StrEnum):
    FIXED = "fixed"
    FROM = "from"
    CUSTOM = "custom"


class BookingStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class ScheduleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str | None] = mapped_column(String(32))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, default="")
    title: Mapped[str] = mapped_column(String(120))
    short_title: Mapped[str] = mapped_column(String(40), default="")
    emoji: Mapped[str] = mapped_column(String(16), default="✨")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    services: Mapped[list["Service"]] = relationship(
        back_populates="category", lazy="selectin"
    )


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (Index("ix_services_category_active", "category_id", "is_active"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    price_mode: Mapped[PriceMode] = mapped_column(enum_col(PriceMode), default=PriceMode.FIXED)
    price: Mapped[int | None] = mapped_column(Integer)
    price_note: Mapped[str | None] = mapped_column(String(200))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=15)
    # 1..N — порядок в блоке «Популярное» на сайте, NULL — не показывать
    featured_rank: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    category: Mapped[Category] = relationship(back_populates="services", lazy="selectin")


class SiteSetting(Base):
    """Пара «ключ — значение» для текстов и контактов на сайте."""

    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )



class WeekdayTemplate(Base):
    __tablename__ = "weekday_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer, unique=True)  # 0 = понедельник
    is_working: Mapped[bool] = mapped_column(Boolean, default=True)
    # [{"start": 600, "end": 1200}, ...] — минуты от полуночи
    windows: Mapped[list[dict]] = mapped_column(JSON, default=list)


class ScheduleDay(Base):
    __tablename__ = "schedule_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[ScheduleStatus] = mapped_column(
        enum_col(ScheduleStatus), default=ScheduleStatus.DRAFT
    )
    note: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    windows: Mapped[list["WorkingWindow"]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WorkingWindow.start_minute",
    )

    def effective_windows(self) -> list[tuple[int, int]]:
        return [(window.start_minute, window.end_minute) for window in self.windows]


class WorkingWindow(Base):
    __tablename__ = "working_windows"
    __table_args__ = (Index("ix_working_windows_day", "day_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("schedule_days.id", ondelete="CASCADE"))
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)

    day: Mapped[ScheduleDay] = relationship(back_populates="windows")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_start", "start_at"),
        Index("ix_bookings_client_status", "client_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[BookingStatus] = mapped_column(
        enum_col(BookingStatus), default=BookingStatus.DRAFT
    )
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    total_minutes: Mapped[int] = mapped_column(Integer, default=0)
    total_price: Mapped[int] = mapped_column(Integer, default=0)
    price_is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    client_name: Mapped[str] = mapped_column(String(128), default="")
    client_phone: Mapped[str] = mapped_column(String(32), default="")
    comment: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(32), default="telegram")

    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_2h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    client_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    client: Mapped[User] = relationship(lazy="selectin")
    items: Mapped[list["BookingItem"]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BookingItem.sort_order",
    )


class BookingItem(Base):
    __tablename__ = "booking_items"
    __table_args__ = (Index("ix_booking_items_booking", "booking_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    title: Mapped[str] = mapped_column(String(160))
    price: Mapped[int] = mapped_column(Integer, default=0)
    price_mode: Mapped[PriceMode] = mapped_column(enum_col(PriceMode), default=PriceMode.FIXED)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    booking: Mapped[Booking] = relationship(back_populates="items")
