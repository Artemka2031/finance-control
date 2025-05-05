# Bot/middleware/error_handling.py
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message


class ErrorHandlingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logging.error(f"Error: {e}", exc_info=True)
            if isinstance(event, Message):
                await event.answer("Произошла ошибка. Попробуйте позже.")
            return None
