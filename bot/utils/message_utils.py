# Bot/utils/message_utils.py
from functools import wraps

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .logging import configure_logger

# Configure utils logger
logger = configure_logger("[UTILS]", "blue")

def delete_messages_after(func):
    @wraps(func)
    async def wrapper(message: Message, state: FSMContext, bot: Bot, *args, **kwargs):
        # Get current state data
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        # Execute the handler
        result = await func(message, state, bot, *args, **kwargs)

        # Delete old messages
        chat_id = message.chat.id
        for msg_id in messages_to_delete:
            try:
                if msg_id:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    logger.debug(f"Deleted message {msg_id} in chat {chat_id}")
            except Exception as e:
                logger.warning(f"Failed to delete message {msg_id} in chat {chat_id}: {e}")

        # Clear the messages_to_delete list in state
        await state.update_data(messages_to_delete=[])

        # Delete the triggering message
        try:
            await message.delete()
            logger.debug(f"Deleted trigger message {message.message_id} in chat {chat_id}")
        except Exception as e:
            logger.warning(f"Failed to delete trigger message {message.message_id} in chat {chat_id}: {e}")

        return result

    return wrapper

def track_message(func):
    """
    Decorator to track messages that should be deleted on state transition.
    """
    @wraps(func)
    async def wrapper(message: Message, state: FSMContext, bot: Bot, *args, **kwargs):
        result = await func(message, state, bot, *args, **kwargs)

        # Get current messages_to_delete
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        # Add new message ID to track
        if isinstance(result, Message):
            messages_to_delete.append(result.message_id)
            logger.debug(f"Tracking message {result.message_id} for deletion")
        elif isinstance(result, dict) and "sent_message" in result:
            messages_to_delete.append(result["sent_message"].message_id)
            logger.debug(f"Tracking message {result['sent_message'].message_id} for deletion")

        # Update state
        await state.update_data(messages_to_delete=messages_to_delete)

        return result

    return wrapper