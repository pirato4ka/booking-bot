from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup


class NavCb(CallbackData, prefix="nav"):
    """Навигация по главному меню: main, book, price, my, about, admin."""

    to: str


class CatCb(CallbackData, prefix="cat"):
    cid: int
    mode: str = "view"  # view | book | add
    page: int = 0


class SvcCb(CallbackData, prefix="svc"):
    sid: int
    mode: str = "view"
    cid: int = 0
    page: int = 0


class PickSvcCb(CallbackData, prefix="pick"):
    sid: int
    mode: str = "book"  # book | add


class DateCb(CallbackData, prefix="dt"):
    date: str
    offset: int = 0


class SlotCb(CallbackData, prefix="sl", sep="|"):
    start: str  # ISO 2026-11-05T14:00


class DraftCb(CallbackData, prefix="dr"):
    action: str  # confirm, ask_confirm, add, time, clear, keep, restart


class MyCb(CallbackData, prefix="my"):
    action: str  # list, card, cancel, cancel_yes, move, ack, decline
    booking_id: int = 0


class AdminCb(CallbackData, prefix="adm"):
    section: str  # menu, schedule, services, bookings, stats, help


class ASvcCb(CallbackData, prefix="as"):
    action: str  # cat, card, add, edit, toggle, move, movecat, del, delete_yes
    sid: int = 0
    cid: int = 0
    page: int = 0


class ACatCb(CallbackData, prefix="ac"):
    action: str  # add, del
    cid: int = 0


class ADayCb(CallbackData, prefix="ad"):
    action: str  # list, open, publish, unpublish, close, restore, copy_prev, preset,
    # publish_week, copy_week, apply_template_all, open_nearest
    date: str = ""
    value: str = ""
    page: int = 0


class AWinCb(CallbackData, prefix="aw"):
    action: str  # pick, add, del
    date: str = ""
    idx: int = 0


class ATimeCb(CallbackData, prefix="at"):
    date: str
    idx: int = 0
    edge: str = "start"  # start | end
    delta: int = 30


class ATplCb(CallbackData, prefix="atp"):
    action: str  # menu, day, set
    wd: int = 0
    value: str = ""


class ABookCb(CallbackData, prefix="ab"):
    action: str  # list, day, card, cancel, cancel_yes, complete, no_show, dates
    booking_id: int = 0
    date: str = ""


class ABookDateCb(CallbackData, prefix="abd"):
    date: str
    offset: int = 0
