# Bot/routers/expenses/date_router.py
from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..expenses.state_classes import Expense
from ...api_client import ApiClient
from ...filters.check_date import CheckDateFilter
from ...keyboards.today import create_today_keyboard, TodayCallback
from ...keyboards.wallet import create_wallet_keyboard
from ...utils.message_utils import delete_messages_after, track_message


def create_date_router(bot: Bot, api_client: ApiClient):
    date_router = Router()

    @date_router.callback_query(Expense.date, TodayCallback.filter())
    @delete_messages_after
    @track_message
    async def change_date(query: CallbackQuery, callback_data: TodayCallback, state: FSMContext, bot: Bot) -> Message:
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        await state.update_data(messages_to_delete=[])

        date = callback_data.today
        await state.update_data(date=date)
        await query.message.edit_text(f"Выбрана дата: {date}", reply_markup=None)

        wallet_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text="Выберите кошелек для расходов:",
            reply_markup=create_wallet_keyboard()
        )
        await state.set_state(Expense.wallet)
        return wallet_message

    @date_router.message(Expense.date, CheckDateFilter())
    @delete_messages_after
    @track_message
    async def set_date_text(message: Message, state: FSMContext, bot: Bot) -> Message:
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        await state.update_data(messages_to_delete=[])

        date = message.text
        await state.update_data(date=date)

        wallet_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Выберите кошелек для расходов:",
            reply_markup=create_wallet_keyboard()
        )
        await state.set_state(Expense.wallet)
        return wallet_message

    @date_router.message(Expense.date)
    @delete_messages_after
    @track_message
    async def invalid_date_format(message: Message, state: FSMContext, bot: Bot) -> Message:
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        if not messages_to_delete:
            sent_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Дата должна быть в формате дд.мм.гг или дд.мм.гггг. Повторите:",
                reply_markup=create_today_keyboard()
            )
            messages_to_delete.append(sent_message.message_id)
            await state.update_data(messages_to_delete=messages_to_delete)

        await state.set_state(Expense.date)
        return sent_message

    return date_router