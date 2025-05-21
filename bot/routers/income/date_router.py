from aiogram import Router, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .state_income import Income
from ...api_client import ApiClient
from ...filters.check_date import CheckDateFilter
from ...keyboards.income_category import create_income_category_keyboard
from ...keyboards.today import create_today_keyboard, TodayCallback
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_message, delete_tracked_messages

logger = configure_logger("[DATE]", "cyan")

def create_date_router(bot: Bot, api_client: ApiClient):
    date_router = Router()

    @date_router.callback_query(Income.date, TodayCallback.filter())
    @track_messages
    async def change_date(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        date = TodayCallback.unpack(query.data).today
        await state.update_data(date=date)

        try:
            await query.message.edit_text(f"Выбрана дата: 🗓️ {html.bold(date)}", reply_markup=None)
            logger.debug(f"Отредактировано сообщение {query.message.message_id} с датой {date}")
            await state.update_data(date_message_id=query.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {query.message.message_id}: {e}")
            new_message = await bot.send_message(
                chat_id=query.message.chat.id,
                text=f"Выбрана дата: 🗓️ {html.bold(date)}",
                reply_markup=None
            )
            await state.update_data(date_message_id=new_message.message_id)
            logger.debug(f"Отправлено новое сообщение {new_message.message_id} с датой {date}")

        await delete_tracked_messages(bot, state, query.message.chat.id)

        category_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text="Выберите категорию дохода: 💵",
            reply_markup=await create_income_category_keyboard(api_client)
        )
        await state.update_data(category_message_id=category_message.message_id)
        await state.set_state(Income.category_code)
        return query.message

    @date_router.message(Income.date, CheckDateFilter())
    @track_messages
    async def set_date_text(message: Message, state: FSMContext, bot: Bot) -> Message:
        date = message.text
        await state.update_data(date=date)

        await delete_message(bot, message.chat.id, message.message_id)

        data = await state.get_data()
        date_message_id = data.get("date_message_id")
        if date_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=date_message_id,
                    text=f"Выбрана дата: 🗓️ {html.bold(date)}",
                    reply_markup=None
                )
                logger.debug(f"Отредактировано сообщение {date_message_id} с датой {date}")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {date_message_id}: {e}")
                new_message = await bot.send_message(
                    chat_id=message.chat.id,
                    text=f"Выбрана дата: 🗓️ {html.bold(date)}",
                    reply_markup=None
                )
                date_message_id = new_message.message_id
                await state.update_data(date_message_id=date_message_id)
                logger.debug(f"Отправлено новое сообщение {date_message_id} с датой {date}")

        await delete_tracked_messages(bot, state, message.chat.id)

        category_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Выберите категорию дохода: 💵",
            reply_markup=await create_income_category_keyboard(api_client)
        )
        await state.update_data(category_message_id=category_message.message_id)
        await state.set_state(Income.category_code)
        return message

    @date_router.message(Income.date)
    @track_messages
    async def invalid_date_format(message: Message, state: FSMContext, bot: Bot) -> Message:
        await delete_message(bot, message.chat.id, message.message_id)
        await delete_tracked_messages(bot, state, message.chat.id)

        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Дата должна быть в формате дд.мм.гг или дд.мм.гггг. Повторите: 🗓️",
            reply_markup=create_today_keyboard()
        )
        await state.update_data(date_message_id=sent_message.message_id)
        await state.set_state(Income.date)
        return sent_message

    return date_router