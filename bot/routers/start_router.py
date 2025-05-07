from aiogram import Router, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..keyboards.start_kb import create_start_kb
from ..utils.logging import configure_logger
from ..utils.message_utils import delete_tracked_messages, delete_key_messages

logger = configure_logger("[START]", "green")


def create_start_router(bot: Bot):
    start_router = Router()

    @start_router.message(CommandStart())
    async def start_command(message: Message, state: FSMContext, bot: Bot) -> Message:
        user_id = message.from_user.id
        chat_id = message.chat.id
        logger.info(f"Пользователь {user_id} вызвал команду /start в чате {chat_id}")

        # Удаляем все сообщения
        await delete_tracked_messages(bot, state, chat_id)
        await delete_key_messages(bot, state, chat_id)
        await state.update_data(messages_to_delete=[])

        # Очищаем состояние
        await state.clear()

        # Отправляем начальное сообщение
        start_message = await bot.send_message(
            chat_id=chat_id,
            text="Добро пожаловать! Выберите операцию: 🔄",
            reply_markup=create_start_kb()
        )
        logger.debug(f"Отправлено начальное сообщение {start_message.message_id} в чате {chat_id}")
        return start_message

    return start_router
