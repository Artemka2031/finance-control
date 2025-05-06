# Bot/routers/income/amount_router.py
from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..income.state_classes import Income
from ...api_client import ApiClient
from ...filters.check_amount import CheckAmountFilter
from ...utils.message_utils import delete_messages_after, track_message


def create_amount_router(bot: Bot, api_client: ApiClient):
    amount_router = Router()

    @amount_router.message(Income.amount, CheckAmountFilter())
    @delete_messages_after
    @track_message
    async def set_amount(message: Message, state: FSMContext):
        amount = float(message.text)
        await state.update_data(amount=amount)
        await message.delete()

        data = await state.get_data()
        amount_message_id = data.get("amount_message_id")
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=amount_message_id,
            text=f"Сумма: {amount} ₽"
        )

        comment_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Введите комментарий (или /skip для пропуска):"
        )
        await state.update_data(comment_message_id=comment_message.message_id)
        await state.set_state(Income.comment)

    @amount_router.message(Income.amount)
    @delete_messages_after
    @track_message
    async def invalid_amount(message: Message, state: FSMContext):
        await message.delete()
        data = await state.get_data()
        if not data.get("extra_messages"):
            error_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Сумма должна быть числом больше 0. Повторите:"
            )
            await state.update_data(extra_messages=[error_message.message_id])
        await state.set_state(Income.amount)

    return amount_router
