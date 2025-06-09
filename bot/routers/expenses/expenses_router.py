from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from api_client import ApiClient
from keyboards.today import create_today_keyboard
from routers.delete_router import create_delete_router
from routers.expenses.amount_router import create_amount_router
from routers.expenses.category_router import create_category_router
from routers.expenses.comment_router import create_comment_router
from routers.expenses.confirm_router import create_confirm_router
from routers.expenses.date_router import create_date_router
from routers.expenses.state_classes import Expense
from routers.expenses.wallet_router import create_wallet_router
from utils.logging import configure_logger
from utils.message_utils import delete_tracked_messages, delete_key_messages, track_messages, delete_message

logger = configure_logger("[EXPENSES]", "yellow")

def create_expenses_router(bot: Bot, api_client: ApiClient):
    expenses_router = Router()

    @expenses_router.message(Command("add_expense"))
    @expenses_router.message(F.text.casefold() == "расход ₽")
    @track_messages
    async def start_expense_adding(message: Message, state: FSMContext, bot: Bot) -> Message:
        # Удаляем все отслеживаемые сообщения предыдущей операции
        await delete_tracked_messages(bot, state, message.chat.id)
        await delete_key_messages(bot, state, message.chat.id)
        await state.update_data(messages_to_delete=[])
        await state.clear()
        # Проверяем, что messages_to_delete пустой
        data = await state.get_data()
        if data.get("messages_to_delete", []):
            logger.warning(f"messages_to_delete не очищен: {data['messages_to_delete']}")
            await state.update_data(messages_to_delete=[])
        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Выберите дату расхода: 🗓️",
            reply_markup=create_today_keyboard()
        )
        await state.set_state(Expense.date)
        return sent_message

    @expenses_router.message(Command("cancel_expense"))
    @expenses_router.message(F.text.casefold() == "отмена расхода")
    @track_messages
    async def cancel_expense_adding(message: Message, state: FSMContext, bot: Bot) -> Message:
        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)
        # Удаляем все отслеживаемые сообщения
        await delete_tracked_messages(bot, state, message.chat.id)
        # Удаляем ключевые сообщения
        await delete_key_messages(bot, state, message.chat.id)
        await state.update_data(messages_to_delete=[])
        await state.clear()
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Добавление расхода отменено 🚫"
        )
        return sent_message

    # Include sub-routers
    expenses_router.include_router(create_date_router(bot, api_client))
    expenses_router.include_router(create_wallet_router(bot, api_client))
    expenses_router.include_router(create_category_router(bot, api_client))
    expenses_router.include_router(create_amount_router(bot, api_client))
    expenses_router.include_router(create_comment_router(bot, api_client))
    expenses_router.include_router(create_confirm_router(bot, api_client))
    expenses_router.include_router(create_delete_router(bot, api_client))

    return expenses_router