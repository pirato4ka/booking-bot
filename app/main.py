from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot.middlewares import DbSessionMiddleware, UserMiddleware
from app.bot.routers import booking, catalog, common, my
from app.bot.routers.admin import setup_admin_router
from app.bootstrap import prepare_database
from app.config import settings
from app.db import dispose_db
from app.scheduler import build_scheduler

logger = logging.getLogger(__name__)



def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.update.outer_middleware(DbSessionMiddleware())
    dispatcher.update.outer_middleware(UserMiddleware())

    # Команды раньше FSM: /start и /cancel должны работать в любом состоянии.
    dispatcher.include_router(common.commands_router)
    # Пользовательские состояния и админка идут раньше fallback из common.
    dispatcher.include_router(setup_admin_router())
    dispatcher.include_router(booking.router)
    dispatcher.include_router(catalog.router)
    dispatcher.include_router(my.router)
    dispatcher.include_router(common.router)
    return dispatcher


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="book", description="Записаться"),
            BotCommand(command="price", description="Услуги и цены"),
            BotCommand(command="my", description="Мои записи"),
            BotCommand(command="cancel", description="Отменить действие"),
            BotCommand(command="help", description="Контакты и помощь"),
        ]
    )


async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан. Заполните .env по образцу .env.example")

    await prepare_database()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    dispatcher = build_dispatcher()
    scheduler = build_scheduler(bot)
    scheduler.start()
    await set_commands(bot)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await dispose_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
