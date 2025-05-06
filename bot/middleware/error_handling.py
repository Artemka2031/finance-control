# Bot/middleware/error_handling.py
from aiogram import BaseMiddleware
from aiogram.types import Update
from loguru import logger


class ErrorHandlingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"[MIDDLEWARE] Error: {e}")
            raise
