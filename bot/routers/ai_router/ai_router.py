from aiogram import Router, Bot
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from api_client import ApiClient
from keyboards.start_kb import create_start_kb
from routers.ai_router.callback_handler import create_callback_router
from routers.ai_router.message_handler import create_message_router
from routers.ai_router.states import MessageState
from utils.logging import configure_logger
from utils.message_utils import track_messages, delete_message, delete_key_messages, delete_tracked_messages

logger = configure_logger("[AI_ROUTER]", "cyan")


def create_ai_router(bot: Bot, api_client: ApiClient) -> Router:
    ai_router = Router(name="ai_router")

    @ai_router.message(Command("start_ai"))
    @track_messages
    async def start_ai(message: Message, state: FSMContext, bot: Bot) -> Message:
        chat_id = message.chat.id
        logger.debug(f"[AI_ROUTER] Handling /start_ai for chat {chat_id}, current state: {await state.get_state()}")

        # Полная очистка состояния
        await state.clear()
        await state.update_data(
            messages_to_delete=[],
            agent_state=None,
            input_text="",
            timer_tasks=[],
            operation_info=""
        )
        data = await state.get_data()
        logger.debug(f"[AI_ROUTER] State after clear: {await state.get_state()}, data: {data}")

        await delete_tracked_messages(bot, state, chat_id)
        await delete_key_messages(bot, state, chat_id)
        await delete_message(bot, chat_id, message.message_id)

        sent_message = await bot.send_message(
            chat_id=chat_id,
            text="🤖 Готов обработать ваш запрос! Напишите <code>#ИИ</code> и ваш запрос или <code>запишите голосовое сообщение</code>, например:\n\n#ИИ Купил кофе за 250 рублей /\n🎙️ Сколько я потратил в прошлом месяце?",
            reply_markup=create_start_kb(),
            parse_mode=ParseMode.HTML
        )
        await state.set_state(MessageState.initial)
        logger.info(f"[AI_ROUTER] Set state to initial for chat {chat_id}, sent message {sent_message.message_id}")
        return sent_message

    @ai_router.message(Command("cancel_ai"))
    @track_messages
    async def cancel_ai(message: Message, state: FSMContext, bot: Bot) -> Message:
        chat_id = message.chat.id
        logger.debug(f"[AI_ROUTER] Handling /cancel_ai for chat {chat_id}, current state: {await state.get_state()}")

        await state.clear()
        await state.update_data(
            messages_to_delete=[],
            agent_state=None,
            input_text="",
            timer_tasks=[],
            operation_info=""
        )
        await delete_message(bot, chat_id, message.message_id)
        await delete_tracked_messages(bot, state, chat_id)
        await delete_key_messages(bot, state, chat_id)

        sent_message = await bot.send_message(
            chat_id=chat_id,
            text="🤖 Обработка ИИ отменена 🚫",
            reply_markup=create_start_kb()
        )
        await state.set_state(MessageState.initial)
        logger.info(f"[AI_ROUTER] Cancelled AI for chat {chat_id}, set state to initial")
        return sent_message

    # @ai_router.message()
    # async def catch_all(message: Message, state: FSMContext, bot: Bot) -> None:
    #     logger.debug(f"[AI_ROUTER] Caught unhandled message: {message.text} in state {await state.get_state()}")
    #     await message.answer("🤔 Пожалуйста, используйте команду /start_ai или #ИИ для операций")

    ai_router.include_router(create_message_router(bot, api_client))
    ai_router.include_router(create_callback_router(bot, api_client))

    return ai_router