from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message


from ..expenses.date_router import create_date_router
from ..expenses.wallet_router import create_wallet_router
from ..expenses.category_router import create_category_router
from ..expenses.amount_router import create_amount_router
from ..expenses.comment_router import create_comment_router
from ..expenses.state_classes import Expense
from ...api_client import ApiClient
from ...keyboards.today import create_today_keyboard
from ...utils.message_utils import delete_messages_after, track_message


def create_expenses_router(bot, api_client: ApiClient):
    expenses_router = Router()

    @expenses_router.message(Command("add_expense"))
    @expenses_router.message(F.text.casefold() == "расход ₽")
    @delete_messages_after
    @track_message
    async def start_expense_adding(message: Message, state: FSMContext) -> Message:
        await state.clear()
        sent_message = await message.answer(
            text="Выберите дату расхода:",
            reply_markup=create_today_keyboard()
        )
        await state.set_state(Expense.date)
        return sent_message

    @expenses_router.message(Command("cancel_expense"))
    @expenses_router.message(F.text.casefold() == "отмена расхода")
    @delete_messages_after
    async def delete_expense_adding(message: Message, state: FSMContext) -> None:
        await message.answer(text="Добавление расхода отменено")
        await state.clear()

    # Include sub-routers
    expenses_router.include_router(create_date_router(bot, api_client))
    expenses_router.include_router(create_wallet_router(bot, api_client))
    expenses_router.include_router(create_category_router(bot, api_client))
    expenses_router.include_router(create_amount_router(bot, api_client))
    expenses_router.include_router(create_comment_router(bot, api_client))

    return expenses_router
