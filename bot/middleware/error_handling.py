from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from bot.utils.logging import configure_logger

logger = configure_logger("[ERROR_MIDDLEWARE]", "red")

class ErrorHandlingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"[MIDDLEWARE] Error: {e}")
            if isinstance(event, CallbackQuery):
                await event.answer("Произошла ошибка, попробуйте снова")
            raise