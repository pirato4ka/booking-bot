from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.exc import IntegrityError

from app.bot.admin_texts import category_admin_text, service_admin_text
from app.bot.keyboards.admin import (
    category_delete_confirm,
    service_card,
    service_delete_confirm,
    service_move_category,
    services_categories,
    services_list,
)
from app.bot.keyboards.client import btn
from app.callbacks import ACatCb, ASvcCb, AdminCb
from app.db.models import PriceMode, Service
from app.filters import IsAdmin
from app.services import catalog
from app.states import CategoryForm, ServiceForm
from app.utils.parsing import parse_duration, parse_price
from app.utils.ui import edit_or_send

router = Router(name="admin_services")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

PAGE_SIZE = 6

FIELD_LABELS = {
    "title": "название",
    "price": "цену",
    "duration": "длительность",
    "buffer": "буфер после услуги",
    "description": "описание",
}

FIELD_PROMPTS = {
    "title": "Введите новое название услуги.",
    "price": "Введите цену: <code>5000</code>, <code>от 3000</code> "
    "или текст вроде <code>2500 + 300 за см²</code>.",
    "duration": "Введите длительность: <code>60</code>, <code>1ч30</code> "
    "или <code>90 мин</code>.",
    "buffer": "Введите буфер после услуги в минутах (0–120).",
    "description": "Введите описание услуги. Отправьте <code>-</code>, чтобы очистить.",
}


def _parse_buffer(raw: str) -> int:
    text = (raw or "").strip()
    if text in {"-", "0", "нет"}:
        return 0
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise ValueError("Введите число минут от 0 до 120")
    value = int(digits)
    if value < 0 or value > 120:
        raise ValueError("Буфер должен быть от 0 до 120 минут")
    return value


async def _render_categories(callback: CallbackQuery, session) -> None:
    categories = await catalog.all_categories(session)
    counts = {category.id: len(category.services) for category in categories}
    if categories:
        text = (
            "<b>💼 Услуги и цены</b>\n\n"
            "Выберите категорию, чтобы изменить услуги, или добавьте новую."
        )
    else:
        text = (
            "<b>💼 Услуги и цены</b>\n\n"
            "Категорий пока нет. Добавьте первую категорию."
        )
    await edit_or_send(callback, text, services_categories(categories, counts))


async def _render_services(
    callback: CallbackQuery, session, category_id: int, page: int = 0
) -> None:
    category = await catalog.get_category(session, category_id)
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        await _render_categories(callback, session)
        return
    services = await catalog.services_by_category(
        session, category_id, include_inactive=True
    )
    total = len(services)
    page = max(0, min(page, max(0, (total - 1) // PAGE_SIZE)))
    page_services = services[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    active_count = sum(1 for service in services if service.is_active)
    await edit_or_send(
        callback,
        category_admin_text(category, total) + f"\n\nАктивных: {active_count}.",
        services_list(
            page_services,
            category_id,
            page,
            (page + 1) * PAGE_SIZE < total,
            active_count,
        ),
    )


async def _render_service_card(
    callback: CallbackQuery, session, service_id: int, category_id: int, page: int = 0
) -> None:
    service = await catalog.get_service(session, service_id)
    if service is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        await _render_services(callback, session, category_id, page)
        return
    await edit_or_send(
        callback,
        service_admin_text(service),
        service_card(service, category_id, page),
    )


async def _prompt(callback: CallbackQuery, text: str, back_callback) -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[btn("⬅️ Отмена", back_callback)]]
    )
    await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(AdminCb.filter(F.section == "services"))
async def services_root(callback: CallbackQuery, session) -> None:
    await callback.answer()
    await _render_categories(callback, session)


@router.callback_query(ASvcCb.filter())
async def on_service_action(
    callback: CallbackQuery, callback_data: ASvcCb, session, state
) -> None:
    action = callback_data.action
    category_id = callback_data.cid
    page = callback_data.page

    if action == "cat":
        await callback.answer()
        await _render_services(callback, session, category_id, page)
        return

    if action == "card":
        await callback.answer()
        await _render_service_card(
            callback, session, callback_data.sid, category_id, page
        )
        return

    if action == "add":
        category = await catalog.get_category(session, category_id)
        if category is None:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        await state.set_state(ServiceForm.title)
        await state.update_data(cid=category_id, page=page)
        await callback.answer()
        await _prompt(
            callback,
            f"<b>Новая услуга в «{category.title}»</b>\n\n"
            "Введите название услуги.",
            ASvcCb(action="cat", cid=category_id, page=page),
        )
        return

    service = await catalog.get_service(session, callback_data.sid)
    if service is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        return

    if action in {
        "edit_title",
        "edit_price",
        "edit_duration",
        "edit_buffer",
        "edit_desc",
    }:
        field = {
            "edit_title": "title",
            "edit_price": "price",
            "edit_duration": "duration",
            "edit_buffer": "buffer",
            "edit_desc": "description",
        }[action]
        await state.set_state(ServiceForm.edit_value)
        await state.update_data(
            service_id=service.id, cid=category_id, page=page, field=field
        )
        await callback.answer()
        await _prompt(
            callback,
            f"<b>{service.title}</b>\n\n"
            f"Изменим {FIELD_LABELS[field]}.\n{FIELD_PROMPTS[field]}",
            ASvcCb(action="card", sid=service.id, cid=category_id, page=page),
        )
        return

    if action == "toggle":
        service.is_active = not service.is_active
        await catalog.save_service(session, service)
        await callback.answer(
            "Услуга возвращена в прайс"
            if service.is_active
            else "Услуга скрыта из прайса"
        )
        await _render_service_card(callback, session, service.id, category_id, page)
        return

    if action == "movecat":
        categories = await catalog.all_categories(session)
        await callback.answer()
        await edit_or_send(
            callback,
            f"<b>{service.title}</b>\n\nВыберите новую категорию.",
            service_move_category(service, categories, category_id),
        )
        return

    if action == "setcat":
        target = await catalog.get_category(session, category_id)
        if target is None:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        service.category_id = target.id
        await catalog.save_service(session, service)
        await callback.answer(f"Перенесено в «{target.title}»")
        await _render_service_card(callback, session, service.id, target.id, 0)
        return

    if action == "del":
        await callback.answer()
        await edit_or_send(
            callback,
            f"Удалить услугу «<b>{service.title}</b>»?",
            service_delete_confirm(service, category_id),
        )
        return

    if action == "delete_yes":
        title = service.title
        await session.delete(service)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            service = await catalog.get_service(session, callback_data.sid)
            if service is not None:
                service.is_active = False
                await catalog.save_service(session, service)
            await callback.answer(
                "Удалить нельзя: услуга есть в записях. Мы скрыли её из прайса.",
                show_alert=True,
            )
            await _render_services(callback, session, category_id, page)
            return
        await callback.answer(f"«{title}» удалена")
        await _render_services(callback, session, category_id, page)
        return

    await callback.answer("Действие пока недоступно", show_alert=True)



@router.callback_query(ACatCb.filter())
async def on_category_action(
    callback: CallbackQuery, callback_data: ACatCb, session, state
) -> None:
    action = callback_data.action

    if action == "add":
        await state.set_state(CategoryForm.title)
        await state.update_data(mode="add")
        await callback.answer()
        await _prompt(
            callback,
            "<b>Новая категория</b>\n\n"
            "Введите название, например: «Массаж».",
            AdminCb(section="services"),
        )
        return

    category = await catalog.get_category(session, callback_data.cid)
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        await _render_categories(callback, session)
        return

    if action == "rename":
        await state.set_state(CategoryForm.title)
        await state.update_data(mode="rename", cid=category.id)
        await callback.answer()
        await _prompt(
            callback,
            f"<b>{category.title}</b>\n\nВведите новое название категории.",
            AdminCb(section="services"),
        )
        return

    if action == "del":
        await callback.answer()
        await edit_or_send(
            callback,
            f"Удалить категорию «<b>{category.title}</b>»?\n\n"
            "Удалить можно только пустую категорию.",
            category_delete_confirm(category),
        )
        return

    if action == "delete_yes":
        try:
            await catalog.delete_category(session, category)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return
        await callback.answer("Категория удалена")
        await _render_categories(callback, session)
        return

    await callback.answer("Действие пока недоступно", show_alert=True)


@router.message(CategoryForm.title)
async def on_category_title(message: Message, state, session) -> None:
    data = await state.get_data()
    title = (message.text or "").strip()
    if not title:
        await message.answer("⚠️ Название не может быть пустым.")
        return
    if len(title) > 120:
        await message.answer("⚠️ Название слишком длинное (максимум 120).")
        return

    if data.get("mode") == "rename":
        category = await catalog.get_category(session, int(data.get("cid") or 0))
        if category is None:
            await state.clear()
            await message.answer("Категория не найдена.")
            return
        await catalog.rename_category(session, category, title)
    else:
        await catalog.create_category(session, title)

    await state.clear()
    categories = await catalog.all_categories(session)
    counts = {item.id: len(item.services) for item in categories}
    await message.answer(
        "<b>💼 Услуги и цены</b>\n\nКатегории обновлены.",
        reply_markup=services_categories(categories, counts),
        parse_mode="HTML",
    )



@router.message(ServiceForm.title)
async def on_service_title(message: Message, state) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("⚠️ Название не может быть пустым.")
        return
    if len(title) > 160:
        await message.answer("⚠️ Название слишком длинное (максимум 160).")
        return
    await state.update_data(title=title)
    await state.set_state(ServiceForm.price)
    await message.answer(
        "Введите цену: <code>5000</code>, <code>от 3000</code> "
        "или текст вроде <code>2500 + 300 за см²</code>.",
        parse_mode="HTML",
    )


@router.message(ServiceForm.price)
async def on_service_price(message: Message, state) -> None:
    try:
        mode, price, note = parse_price(message.text or "")
    except ValueError as error:
        await message.answer(f"⚠️ {error}")
        return
    await state.update_data(
        price_mode=mode.value, price=price, price_note=note
    )
    await state.set_state(ServiceForm.duration)
    await message.answer(
        "Введите длительность: <code>60</code>, <code>1ч30</code> "
        "или <code>90 мин</code>.",
        parse_mode="HTML",
    )


@router.message(ServiceForm.duration)
async def on_service_duration(message: Message, state) -> None:
    try:
        duration = parse_duration(message.text or "")
    except ValueError as error:
        await message.answer(f"⚠️ {error}")
        return
    await state.update_data(duration=duration)
    await state.set_state(ServiceForm.buffer)
    await message.answer("Буфер после услуги в минутах (0–120):")


@router.message(ServiceForm.buffer)
async def on_service_buffer(message: Message, state) -> None:
    try:
        buffer_minutes = _parse_buffer(message.text or "")
    except ValueError as error:
        await message.answer(f"⚠️ {error}")
        return
    await state.update_data(buffer=buffer_minutes)
    await state.set_state(ServiceForm.description)
    await message.answer(
        "Добавьте описание услуги или отправьте <code>-</code>, чтобы пропустить.",
        parse_mode="HTML",
    )


@router.message(ServiceForm.description)
async def on_service_description(message: Message, state, session) -> None:
    data = await state.get_data()
    description = (message.text or "").strip()
    if description == "-":
        description = ""
    category_id = int(data.get("cid") or 0)
    if await catalog.get_category(session, category_id) is None:
        await state.clear()
        await message.answer("Категория не найдена.")
        return
    try:
        service = await catalog.create_service(
            session,
            category_id=category_id,
            title=str(data.get("title") or ""),
            price_mode=PriceMode(str(data.get("price_mode") or "fixed")),
            price=data.get("price"),
            price_note=data.get("price_note"),
            duration_minutes=int(data.get("duration") or 60),
            buffer_minutes=int(data.get("buffer") or 0),
            description=description,
        )
    except ValueError as error:
        await message.answer(f"⚠️ {error}")
        return
    page = int(data.get("page") or 0)
    await state.clear()
    await message.answer(
        service_admin_text(service),
        reply_markup=service_card(service, category_id, page),
        parse_mode="HTML",
    )



@router.message(ServiceForm.edit_value)
async def on_service_edit_value(message: Message, state, session) -> None:
    data = await state.get_data()
    service = await catalog.get_service(session, int(data.get("service_id") or 0))
    if service is None:
        await state.clear()
        await message.answer("Услуга не найдена.")
        return

    field = str(data.get("field") or "")
    raw = (message.text or "").strip()
    try:
        if field == "title":
            if not raw:
                raise ValueError("Название не может быть пустым")
            service.title = raw[:160]
        elif field == "price":
            mode, price, note = parse_price(raw)
            service.price_mode = mode
            service.price = price
            service.price_note = note
        elif field == "duration":
            service.duration_minutes = parse_duration(raw)
        elif field == "buffer":
            service.buffer_minutes = _parse_buffer(raw)
        elif field == "description":
            service.description = "" if raw == "-" else raw
        else:
            raise ValueError("Неизвестное поле")
    except ValueError as error:
        await message.answer(f"⚠️ {error}")
        return

    await catalog.save_service(session, service)
    category_id = int(data.get("cid") or service.category_id)
    page = int(data.get("page") or 0)
    await state.clear()
    await message.answer(
        service_admin_text(service),
        reply_markup=service_card(service, category_id, page),
        parse_mode="HTML",
    )

