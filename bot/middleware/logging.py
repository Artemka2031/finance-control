# Bot/middleware/logging.py
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineQuery


class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = getattr(event.from_user, 'id', 'unknown')

        if isinstance(event, Message):
            logging.info(f"Message from {user_id}: text='{event.text}', chat_id={event.chat.id}")
        elif isinstance(event, CallbackQuery):
            logging.info(
                f"CallbackQuery from {user_id}: data='{event.data}', message_id={event.message.message_id if event.message else 'inline'}")
        elif isinstance(event, InlineQuery):
            logging.info(f"InlineQuery from {user_id}: query='{event.query}'")
        else:
            logging.info(f"Event from {user_id}: type={type(event).__name__}")

        return await handler(event, data)
