from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BookingFlow(StatesGroup):
    """Выбор даты/времени и ввод телефона."""

    pick_date = State()
    phone = State()
    name = State()
    comment = State()


class ScheduleAdmin(StatesGroup):
    """Ручной ввод окон расписания текстом."""

    windows = State()


class ServiceForm(StatesGroup):
    title = State()
    price = State()
    duration = State()
    buffer = State()
    description = State()
    edit_value = State()


class CategoryForm(StatesGroup):
    title = State()
