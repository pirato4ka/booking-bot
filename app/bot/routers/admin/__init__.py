from __future__ import annotations

from aiogram import Router

from app.bot.routers.admin import bookings, menu, schedule, services, stats


def setup_admin_router() -> Router:
    root = Router(name="admin")
    root.include_router(menu.router)
    root.include_router(stats.router)
    root.include_router(services.router)
    root.include_router(bookings.router)
    root.include_router(schedule.router)
    return root
