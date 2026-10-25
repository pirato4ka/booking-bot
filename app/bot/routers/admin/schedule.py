from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.admin_texts import day_editor_text, schedule_list_text, template_text
from app.bot.keyboards.admin import (
    schedule_day,
    schedule_list,
    template_day,
    templates_menu,
)
from app.bot.keyboards.client import btn
from app.callbacks import ADayCb, AdminCb, ATplCb, ATimeCb, AWinCb
from app.config import settings
from app.db.models import ScheduleStatus
from app.filters import IsAdmin
from app.services import schedule as schedule_service
from app.services.schedule import PRESETS
from app.states import ScheduleAdmin
from app.utils.parsing import parse_windows
from app.utils.timeutil import today
from app.utils.ui import edit_or_send

router = Router(name="admin_schedule")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

PAGE_SIZE = 7


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


async def _render_list(callback: CallbackQuery, session, page: int = 0) -> None:
    await schedule_service.ensure_horizon(session)
    days = await schedule_service.overview(
        session, today(), settings.schedule_horizon_days
    )
    total = len(days)
    page = max(0, min(page, max(0, (total - 1) // PAGE_SIZE)))
    page_days = days[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    counts = {info.date: info.bookings for info in days}
    drafts_total = sum(1 for info in days if info.status == ScheduleStatus.DRAFT)
    await edit_or_send(
        callback,
        schedule_list_text(
            page_days, page, settings.schedule_horizon_days, drafts_total
        ),
        schedule_list(
            page_days,
            page,
            counts,
            page > 0,
            (page + 1) * PAGE_SIZE < total,
        ),
    )


async def _render_day(callback: CallbackQuery, session, day_date: date) -> None:
    day = await schedule_service.get_or_create_day(session, day_date)
    info = await schedule_service.day_info(session, day_date)
    await edit_or_send(
        callback, day_editor_text(day, info.bookings), schedule_day(day)
    )


@router.callback_query(AdminCb.filter(F.section == "schedule"))
async def schedule_root(callback: CallbackQuery, session, state) -> None:
    await state.clear()
    await callback.answer()
    await _render_list(callback, session, 0)


@router.callback_query(AdminCb.filter(F.section == "templates"))
async def templates_root(callback: CallbackQuery, session) -> None:
    templates = await schedule_service.templates_list(session)
    await callback.answer()
    await edit_or_send(
        callback,
        "<b>📖 Шаблон недели</b>\n\n"
        "Шаблон подставляется в новые дни и по кнопке «Из шаблона».",
        templates_menu(templates),
    )


@router.callback_query(ADayCb.filter())
async def on_day_action(
    callback: CallbackQuery, callback_data: ADayCb, session, state
) -> None:
    action = callback_data.action

    if action == "list":
        await callback.answer()
        await _render_list(callback, session, callback_data.page)
        return

    if action in {"publish_drafts", "copy_week", "publish_week"}:
        await state.clear()
        if action == "publish_drafts":
            published, closed = await schedule_service.publish_drafts(session)
            await callback.answer(f"Опубликовано: {published}, закрыто: {closed}")
        elif action == "copy_week":
            copied, conflicts = await schedule_service.copy_week(session, today())
            note = f"Скопировано дней: {copied}"
            if conflicts:
                note += f"; проверьте дни с записями: {len(conflicts)}"
            await callback.answer(note)
        else:
            published = await schedule_service.publish_week(session, today())
            await callback.answer(f"Опубликовано дней: {published}")
        await _render_list(callback, session)
        return

    day_date = _parse_date(callback_data.date) if callback_data.date else None
    if day_date is None:
        await callback.answer("Не удалось определить дату", show_alert=True)
        return

    if action == "open":
        await callback.answer()
        await _render_day(callback, session, day_date)
        return

    if action == "publish":
        ok = await schedule_service.publish_day(session, day_date)
        await callback.answer(
            "День опубликован" if ok else "Сначала задайте рабочие окна",
            show_alert=not ok,
        )
        await _render_day(callback, session, day_date)
        return

    if action == "close":
        await schedule_service.close_day(session, day_date)
        await callback.answer("День закрыт для записи")
        await _render_day(callback, session, day_date)
        return

    if action == "preset":
        day = await schedule_service.get_or_create_day(session, day_date)
        if not schedule_service.apply_preset(day, callback_data.value):
            await callback.answer("Неизвестный шаблон", show_alert=True)
            return
        if day.status != ScheduleStatus.PUBLISHED:
            day.status = ScheduleStatus.DRAFT
        await session.commit()
        await callback.answer("Окна обновлены")
        await _render_day(callback, session, day_date)
        return

    if action == "copy_prev":
        ok = await schedule_service.copy_previous_day(session, day_date)
        await callback.answer(
            "Скопировано с предыдущего дня"
            if ok
            else "Предыдущий день не найден",
            show_alert=not ok,
        )
        await _render_day(callback, session, day_date)
        return

    if action == "apply_template":
        ok = await schedule_service.apply_template_to_day(session, day_date)
        await callback.answer(
            "Шаблон применён" if ok else "В шаблоне выходной день",
            show_alert=not ok,
        )
        await _render_day(callback, session, day_date)
        return

    await callback.answer("Действие пока недоступно", show_alert=True)


@router.callback_query(ATimeCb.filter())
async def on_time_action(
    callback: CallbackQuery, callback_data: ATimeCb, session
) -> None:
    day_date = _parse_date(callback_data.date)
    if day_date is None:
        await callback.answer("Не удалось определить дату", show_alert=True)
        return
    ok = await schedule_service.shift_window(
        session,
        day_date,
        callback_data.idx,
        callback_data.edge,
        callback_data.delta,
    )
    await callback.answer("" if ok else "Дальше сдвинуть нельзя")
    await _render_day(callback, session, day_date)


@router.callback_query(AWinCb.filter())
async def on_window_action(
    callback: CallbackQuery, callback_data: AWinCb, session, state
) -> None:
    day_date = _parse_date(callback_data.date)
    if day_date is None:
        await callback.answer("Не удалось определить дату", show_alert=True)
        return

    if callback_data.action == "add":
        ok = await schedule_service.add_window(session, day_date)
        await callback.answer(
            "Окно добавлено" if ok else "Больше окон на этот день не добавить",
            show_alert=not ok,
        )
        await _render_day(callback, session, day_date)
        return

    if callback_data.action == "del":
        ok = await schedule_service.delete_window(
            session, day_date, callback_data.idx
        )
        await callback.answer("" if ok else "Окно не найдено")
        await _render_day(callback, session, day_date)
        return

    if callback_data.action == "input":
        await state.set_state(ScheduleAdmin.windows)
        await state.update_data(target="day", date=day_date.isoformat())
        await callback.answer()
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [btn("⬅️ К дню", ADayCb(action="open", date=day_date.isoformat()))]
            ]
        )
        await callback.message.answer(
            "<b>Введите окна работы</b>\n\n"
            "Например: <code>10:00-14:00, 15:00-20:00</code>",
            reply_markup=markup,
            parse_mode="HTML",
        )
        return

    await callback.answer("Действие пока недоступно", show_alert=True)


@router.callback_query(ATplCb.filter())
async def on_template_action(
    callback: CallbackQuery, callback_data: ATplCb, session, state
) -> None:
    action = callback_data.action

    if action == "menu":
        templates = await schedule_service.templates_list(session)
        await callback.answer()
        await edit_or_send(
            callback,
            "<b>📖 Шаблон недели</b>\n\n"
            "Шаблон подставляется в новые дни и по кнопке «Из шаблона».",
            templates_menu(templates),
        )
        return

    weekday = callback_data.wd
    if not 0 <= weekday <= 6:
        await callback.answer("Неверный день недели", show_alert=True)
        return

    if action == "day":
        templates = await schedule_service.templates_map(session)
        windows = schedule_service.normalize_template_windows(
            templates[weekday].windows
        )
        await callback.answer()
        await edit_or_send(
            callback, template_text(weekday, windows), template_day(weekday)
        )
        return

    if action == "set":
        if callback_data.value == "off":
            windows: list[tuple[int, int]] = []
        else:
            preset = PRESETS.get(callback_data.value)
            if preset is None:
                await callback.answer("Неизвестный шаблон", show_alert=True)
                return
            windows = list(preset[1])
        await schedule_service.save_template(session, weekday, windows)
        await callback.answer("Шаблон обновлён")
        await edit_or_send(
            callback, template_text(weekday, windows), template_day(weekday)
        )
        return

    if action == "custom":
        await state.set_state(ScheduleAdmin.windows)
        await state.update_data(target="template", weekday=weekday)
        await callback.answer()
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[btn("⬅️ К шаблону", ATplCb(action="menu"))]]
        )
        await callback.message.answer(
            "<b>Введите окна для шаблона</b>\n\n"
            "Например: <code>10:00-14:00, 15:00-20:00</code>",
            reply_markup=markup,
            parse_mode="HTML",
        )
        return

    await callback.answer("Действие пока недоступно", show_alert=True)



@router.message(ScheduleAdmin.windows)
async def on_windows_input(message: Message, state, session) -> None:
    data = await state.get_data()
    try:
        windows = parse_windows(message.text or "")
    except ValueError as error:
        await message.answer(f"⚠️ {error}")
        return

    target = data.get("target")
    await state.clear()

    if target == "template":
        weekday = int(data.get("weekday") or 0)
        if not 0 <= weekday <= 6:
            await message.answer("Не удалось определить день недели.")
            return
        await schedule_service.save_template(session, weekday, windows)
        await message.answer(
            template_text(weekday, windows),
            reply_markup=template_day(weekday),
            parse_mode="HTML",
        )
        return

    day_date = _parse_date(str(data.get("date") or ""))
    if day_date is None:
        await message.answer("Не удалось определить дату.")
        return
    day = await schedule_service.get_or_create_day(session, day_date)
    schedule_service.replace_windows(day, windows)
    if day.status != ScheduleStatus.PUBLISHED:
        day.status = ScheduleStatus.DRAFT
    await session.commit()
    day = await schedule_service.get_or_create_day(session, day_date)
    info = await schedule_service.day_info(session, day_date)
    await message.answer(
        day_editor_text(day, info.bookings),
        reply_markup=schedule_day(day),
        parse_mode="HTML",
    )

