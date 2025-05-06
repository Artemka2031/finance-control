# Bot/routers/expenses/expenses_router.py
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..expenses.amount_router import create_amount_router
from ..expenses.category_router import create_category_router
from ..expenses.comment_router import create_comment_router
from ..expenses.date_router import create_date_router
from ..expenses.state_classes import Expense
from ..expenses.wallet_router import create_wallet_router
from ...api_client import ApiClient
from ...keyboards.today import create_today_keyboard
from ...utils.logging import configure_logger
from ...utils.message_utils import delete_messages_after, track_message

logger = configure_logger("[EXPENSES]", "yellow")

def create_expenses_router(bot: Bot, api_client: ApiClient):
    expenses_router = Router()

    @expenses_router.message(Command("add_expense"))
    @expenses_router.message(F.text.casefold() == "расход ₽")
    @delete_messages_after
    @track_message
    async def start_expense_adding(message: Message, state: FSMContext, bot: Bot) -> Message:
        await state.clear()
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Выберите дату расхода:",
            reply_markup=create_today_keyboard()
        )
        await state.set_state(Expense.date)
        return sent_message

    @expenses_router.message(Command("cancel_expense"))
    @expenses_router.message(F.text.casefold() == "отмена расхода")
    @delete_messages_after
    async def cancel_expense_adding(message: Message, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        chat_id = message.chat.id

        for msg_id in messages_to_delete:
            try:
                if msg_id:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Failed to delete message {msg_id} in chat {chat_id}: {e}")

        await state.update_data(messages_to_delete=[])
        await bot.send_message(chat_id=chat_id, text="Добавление расхода отменено")
        await state.clear()

    # Include sub-routers
    expenses_router.include_router(create_date_router(bot, api_client))
    expenses_router.include_router(create_wallet_router(bot, api_client))
    expenses_router.include_router(create_category_router(bot, api_client))
    expenses_router.include_router(create_amount_router(bot, api_client))
    expenses_router.include_router(create_comment_router(bot, api_client))

    return expenses_router