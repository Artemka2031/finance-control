from aiogram import Router, Bot, F, html
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from api_client import ApiClient
from keyboards.confirm import create_confirm_keyboard
from routers.income.state_income import Income
from utils.logging import configure_logger
from utils.message_utils import track_messages, delete_message, delete_key_messages, delete_tracked_messages

logger = configure_logger("[COMMENT]", "cyan")

def create_comment_router(bot: Bot, api_client: ApiClient):
    comment_router = Router()

    @comment_router.message(Income.comment, F.text)
    @track_messages
    async def set_comment(message: Message, state: FSMContext, bot: Bot) -> Message:
        user_id = message.from_user.id
        chat_id = message.chat.id
        comment = message.text
        data = await state.get_data()

        logger.info(f"Пользователь {user_id} добавил комментарий '{comment}'")

        await state.update_data(comment=comment)
        await state.set_state(Income.confirm)

        operation_info = await format_income_message(data, api_client)

        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=f"Подтвердите операцию:\n{operation_info}\n\nНажмите кнопку для подтверждения: ✅",
            reply_markup=create_confirm_keyboard(),
            parse_mode="HTML"
        )
        await state.update_data(comment_message_id=sent_message.message_id)

        await delete_message(bot, chat_id, message.message_id)
        await delete_tracked_messages(bot, state, chat_id, exclude_message_id=sent_message.message_id)
        await delete_key_messages(bot, state, chat_id, exclude_message_id=sent_message.message_id)

        logger.info(f"Переход в состояние Income.confirm, отправлено сообщение {sent_message.message_id}")
        return sent_message

    async def format_income_message(data: dict, api_client: ApiClient) -> str:
        date = data.get("date", "")
        category_code = data.get("category_code", "")
        amount = data.get("amount", 0)
        comment = data.get("comment", "")

        category_name = ""
        try:
            if category_code:
                categories = await api_client.get_incomes()
                category_name = next((cat.name for cat in categories if cat.code == category_code), category_code)
            logger.debug(f"Retrieved category name: {category_name}")
        except Exception as e:
            logger.warning(f"Error retrieving category name: {e}")

        message_lines = []
        if date:
            message_lines.append(f"Дата: 🗓️ {html.code(date)}")
        if category_name:
            message_lines.append(f"Категория: 🏷️ {html.code(category_name)}")
        if amount:
            message_lines.append(f"Сумма: 💰 {html.code(amount)} ₽")
        if comment:
            message_lines.append(f"Комментарий: 💬 {html.code(comment)}")

        return "\n".join(message_lines)

    return comment_router