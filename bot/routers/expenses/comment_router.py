from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from api_client import ApiClient
from keyboards.confirm import create_confirm_keyboard
from routers.expenses.state_classes import Expense
from utils.logging import configure_logger
from utils.message_utils import track_messages, format_operation_message, delete_message, delete_key_messages, \
    delete_tracked_messages

logger = configure_logger("[COMMENT]", "cyan")

def create_comment_router(bot: Bot, api_client: ApiClient):
    comment_router = Router()

    @comment_router.message(Expense.comment, F.text)
    @track_messages
    async def set_comment(message: Message, state: FSMContext, bot: Bot) -> Message:
        user_id = message.from_user.id
        chat_id = message.chat.id
        comment = message.text
        data = await state.get_data()

        logger.info(f"Пользователь {user_id} добавил комментарий '{comment}'")

        # Сохраняем комментарий
        await state.update_data(comment=comment)
        await state.set_state(Expense.confirm)

        # Форматируем сообщение с полной информацией об операции
        operation_info = await format_operation_message(data, api_client)

        # Отправляем сообщение подтверждения с полной информацией
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=f"Подтвердите операцию:\n{operation_info}\n\nНажмите кнопку для подтверждения: ✅",
            reply_markup=create_confirm_keyboard(),
            parse_mode="HTML"
        )
        await state.update_data(comment_message_id=sent_message.message_id)

        # Удаляем сообщение пользователя
        await delete_message(bot, chat_id, message.message_id)

        # Удаляем временные и ключевые сообщения, исключая новое сообщение
        await delete_tracked_messages(bot, state, chat_id, exclude_message_id=sent_message.message_id)
        await delete_key_messages(bot, state, chat_id, exclude_message_id=sent_message.message_id)

        logger.info(f"Переход в состояние Expense.confirm, отправлено сообщение {sent_message.message_id}")
        return sent_message

    return comment_router