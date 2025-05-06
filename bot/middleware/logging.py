# Bot/middleware/logging.py
from aiogram import BaseMiddleware
from aiogram.types import Update
from ..utils.logging import configure_logger

# Configure middleware logger
logger = configure_logger("[MIDDLEWARE]", "magenta")

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        # Log entry to middleware
        logger.debug("Entering LoggingMiddleware")

        # Extract the user ID from the appropriate sub-event
        user_id = 'unknown'
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
            logger.debug(f"Processing message event for user {user_id}")
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id
            logger.debug(f"Processing callback query event for user {user_id}")
        elif event.inline_query and event.inline_query.from_user:
            user_id = event.inline_query.from_user.id
            logger.debug(f"Processing inline query event for user {user_id}")
        elif event.edited_message and event.edited_message.from_user:
            user_id = event.edited_message.from_user.id
            logger.debug(f"Processing edited message event for user {user_id}")
        elif event.channel_post and event.channel_post.from_user:
            user_id = event.channel_post.from_user.id
            logger.debug(f"Processing channel post event for user {user_id}")
        elif event.edited_channel_post and event.edited_channel_post.from_user:
            user_id = event.edited_channel_post.from_user.id
            logger.debug(f"Processing edited channel post event for user {user_id}")
        else:
            logger.warning(f"Unknown event type: {type(event).__name__}")

        # Log based on event type
        if event.message:
            logger.info(
                f"Message from {user_id}: text='{event.message.text}', chat_id={event.message.chat.id}")
        elif event.callback_query:
            logger.info(
                f"CallbackQuery from {user_id}: data='{event.callback_query.data}', "
                f"message_id={event.callback_query.message.message_id if event.callback_query.message else 'inline'}"
            )
        elif event.inline_query:
            logger.info(f"InlineQuery from {user_id}: query='{event.inline_query.query}'")
        else:
            logger.info(f"Event from {user_id}: type {type(event).__name__}")

        try:
            result = await handler(event, data)
            logger.debug(f"Handler completed for user {user_id}")
            return result
        except Exception as e:
            logger.error(f"Handler failed for user {user_id}: {e}")
            raise