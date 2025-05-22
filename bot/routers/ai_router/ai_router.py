from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from .message_handler import create_message_router
from .callback_handler import create_callback_router
from .states import MessageState
from ...api_client import ApiClient
from ...keyboards.start_kb import create_start_kb
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_message, delete_tracked_messages, delete_key_messages

logger = configure_logger("[AI_ROUTER]", "cyan")


def create_ai_router(bot: Bot, api_client: ApiClient) -> Router:
    ai_router = Router()

    @ai_router.message(Command("start_ai"))
    @track_messages
    async def start_ai(message: Message, state: FSMContext, bot: Bot) -> Message:
        await delete_tracked_messages(bot, state, message.chat.id)
        await delete_key_messages(bot, state, message.chat.id)
        await state.update_data(messages_to_delete=[])
        await state.clear()
        data = await state.get_data()
        if data.get("messages_to_delete", []):
            logger.warning(f"messages_to_delete не очищен: {data['messages_to_delete']}")
            await state.update_data(messages_to_delete=[])
        await delete_message(bot, message.chat.id, message.message_id)
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="🤖 Готов обработать ваш запрос! Напишите #ИИ и ваш запрос, например: #ИИ Купил кофе за 250",
            reply_markup=create_start_kb()
        )
        await state.set_state(MessageState.waiting_for_ai_input)
        return sent_message

    @ai_router.message(Command("cancel_ai"))
    @track_messages
    async def cancel_ai(message: Message, state: FSMContext, bot: Bot) -> Message:
        await delete_message(bot, message.chat.id, message.message_id)
        await delete_tracked_messages(bot, state, message.chat.id)
        await delete_key_messages(bot, state, message.chat.id)
        await state.update_data(messages_to_delete=[])
        await state.clear()
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="🤖 Обработка ИИ отменена 🚫",
            reply_markup=create_start_kb()
        )
        await state.set_state(MessageState.waiting_for_ai_input)
        return sent_message

    ai_router.include_router(create_message_router(bot, api_client))
    ai_router.include_router(create_callback_router(bot, api_client))

    return ai_router
