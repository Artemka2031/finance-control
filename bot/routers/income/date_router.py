# Bot/routers/income/date_router.py
from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from ...filters.check_date import CheckDateFilter
from ...keyboards.today import create_today_keyboard, TodayCallback
# from ...keyboards.category import chapters_choose_kb
from ..income.state_classes import Income
from ...utils.message_utils import delete_messages_after, track_message
from ...api_client import ApiClient

def create_date_router(bot: Bot, api_client: ApiClient):
    date_router = Router()

    @date_router.callback_query(Income.date, TodayCallback.filter())
    @delete_messages_after
    @track_message
    async def change_date(query: CallbackQuery, callback_data: TodayCallback, state: FSMContext):
        chat_id = query.message.chat.id
        data = await state.get_data()

        # Delete extra messages if they exist
        extra_messages = data.get("extra_messages", [])
        for message_id in extra_messages:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        await state.update_data(extra_messages=[])

        date = callback_data.today
        await query.message.edit_text(f"Выбрана дата: {date}", reply_markup=None)
        await state.update_data(date=date)

        # Fetch categories from Google Sheets (via api_client)
        categories = await api_client.get_coming_categories()

        category_message = await query.message.edit_text(
            text="Выберите категорию прихода:",
            # reply_markup=chapters_choose_kb(categories)
        )
        await state.update_data(category_message_id=category_message.message_id)
        await state.set_state(Income.chapter_code)

    @date_router.message(Income.date, CheckDateFilter())
    @delete_messages_after
    @track_message
    async def set_date_text(message: Message, state: FSMContext):
        date = message.text
        chat_id = message.chat.id
        data = await state.get_data()

        # Delete extra messages if they exist
        extra_messages = data.get("extra_messages", [])
        for message_id in extra_messages:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        await state.update_data(extra_messages=[])

        await message.delete()

        date_message_id = data.get("date_message_id")
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=date_message_id,
            text=f"Выбрана дата: {date}",
            reply_markup=None
        )
        await state.update_data(date=date)

        # Fetch categories from Google Sheets (via api_client)
        categories = await api_client.get_coming_categories()

        category_message = await bot.send_message(
            chat_id=chat_id,
            text="Выберите категорию прихода:",
            # reply_markup=chapters_choose_kb(categories)
        )
        await state.update_data(category_message_id=category_message.message_id)
        await state.set_state(Income.chapter_code)

    @date_router.message(Income.date)
    @delete_messages_after
    @track_message
    async def invalid_date_format(message: Message, state: FSMContext):
        await message.delete()
        data = await state.get_data()

        # Only send error message if not already sent
        if not data.get("extra_messages"):
            incorrect_date_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Дата должна быть в формате дд.мм.гггг и не позднее сегодняшнего дня. Повторите:",
                reply_markup=create_today_keyboard()
            )
            await state.update_data(extra_messages=[incorrect_date_message.message_id])

        await state.set_state(Income.date)

    return date_router