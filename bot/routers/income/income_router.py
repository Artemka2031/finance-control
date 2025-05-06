# Bot/routers/income/income_router.py
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..income.amount_router import create_amount_router
# from ..income.category_router import create_category_router
from ..income.comment_router import create_comment_router
from ..income.date_router import create_date_router
from ..income.state_classes import Income
from ...api_client import ApiClient
from ...keyboards.today import create_today_keyboard
from ...utils.message_utils import delete_messages_after, track_message


def create_income_router(bot: Bot, api_client: ApiClient):
    income_router = Router()

    @income_router.message(Command("add_income"))
    @income_router.message(F.text.casefold() == "приход ₽")
    @delete_messages_after
    @track_message
    async def start_income_adding(message: Message, state: FSMContext) -> None:
        await state.clear()
        sent_message = await message.answer(
            text="Выберите дату прихода:",
            reply_markup=create_today_keyboard()
        )
        await state.update_data(date_message_id=sent_message.message_id)
        await state.set_state(Income.date)

    @income_router.message(Command("cancel_income"))
    @income_router.message(F.text.casefold() == "отмена прихода")
    @delete_messages_after
    async def cancel_income_adding(message: Message, state: FSMContext) -> None:
        chat_id = message.chat.id
        data = await state.get_data()
        await message.delete()

        fields_to_check = ["date_message_id", "category_message_id", "amount_message_id", "comment_message_id"]
        delete_messages = [data[field] for field in fields_to_check if field in data]

        extra_messages = data.get("extra_messages", [])
        delete_messages.extend(extra_messages)

        for message_id in delete_messages:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)

        await message.answer(text="Добавление прихода отменено")
        await state.clear()

    # Include sub-routers
    income_router.include_router(create_date_router(bot, api_client))
    # income_router.include_router(create_category_router(bot, api_client))
    income_router.include_router(create_amount_router(bot, api_client))
    income_router.include_router(create_comment_router(bot, api_client))

    return income_router
