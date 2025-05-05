# Bot/routers/expenses/amount_router.py
from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.api_client import ApiClient
from bot.filters.check_amount import CheckAmountFilter
from bot.routers.expenses.state_classes import Expense
from bot.utils.message_utils import delete_messages_after, track_message


def create_amount_router(bot: Bot, api_client: ApiClient):
    amount_router = Router()

    @amount_router.message(Expense.amount, CheckAmountFilter())
    @delete_messages_after
    @track_message
    async def set_amount(message: Message, state: FSMContext, bot: Bot) -> Message:
        amount = float(message.text.replace(',', '.'))
        await state.update_data(amount=amount)

        data = await state.get_data()
        wallet = data["wallet"]

        if wallet == "borrow":
            saving_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Введите коэффициент экономии:"
            )
            await state.set_state(Expense.coefficient)
            return saving_message
        else:
            comment_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Введите комментарий:"
            )
            await state.set_state(Expense.comment)
            return comment_message

    @amount_router.message(Expense.amount)
    @delete_messages_after
    @track_message
    async def incorrect_amount(message: Message, state: FSMContext, bot: Bot) -> Message:
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Введено недопустимое значение. Должны быть только числа больше 0. Разделяющий знак = ','"
        )
        await state.set_state(Expense.amount)
        return sent_message

    @amount_router.message(Expense.coefficient)
    @delete_messages_after
    @track_message
    async def set_coefficient(message: Message, state: FSMContext, bot: Bot) -> Message:
        try:
            coefficient = float(message.text.replace(',', '.'))
            if coefficient <= 0:
                raise ValueError("Коэффициент должен быть больше 0")
        except ValueError:
            sent_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Введено недопустимое значение. Должны быть только числа больше 0. Разделяющий знак = ','"
            )
            await state.set_state(Expense.coefficient)
            return sent_message

        await state.update_data(coefficient=coefficient)

        comment_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Введите комментарий:"
        )
        await state.set_state(Expense.comment)
        return comment_message

    return amount_router
