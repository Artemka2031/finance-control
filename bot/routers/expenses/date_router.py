from aiogram import Router, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from api_client import ApiClient
from filters.check_date import CheckDateFilter
from keyboards.today import create_today_keyboard
from keyboards.utils import TodayCallback
from keyboards.wallet import create_wallet_keyboard
from routers.expenses.state_classes import Expense
from utils.logging import configure_logger
from utils.message_utils import track_messages, delete_tracked_messages, delete_message

logger = configure_logger("[DATE]", "cyan")

def create_date_router(bot: Bot, api_client: ApiClient):
    date_router = Router()

    @date_router.callback_query(Expense.date, TodayCallback.filter())
    @track_messages
    async def change_date(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        date = TodayCallback.unpack(query.data).today
        await state.update_data(date=date)

        # Редактируем сообщение бота и сохраняем как ключевое
        try:
            await query.message.edit_text(f"Выбрана дата: 🗓️ {html.bold(date)}", reply_markup=None)
            logger.debug(f"Отредактировано сообщение {query.message.message_id} с датой {date}")
            await state.update_data(date_message_id=query.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {query.message.message_id}: {e}")
            # Отправляем новое сообщение
            new_message = await bot.send_message(
                chat_id=query.message.chat.id,
                text=f"Выбрана дата: 🗓️ {html.bold(date)}",
                reply_markup=None
            )
            await state.update_data(date_message_id=new_message.message_id)
            logger.debug(f"Отправлено новое сообщение {new_message.message_id} с датой {date}")

        # Удаляем временные сообщения после сохранения ключевого
        await delete_tracked_messages(bot, state, query.message.chat.id)

        # Отправляем новое сообщение для выбора кошелька
        wallet_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text="Выберите кошелёк для расходов: 💸",
            reply_markup=create_wallet_keyboard()
        )
        await state.update_data(wallet_message_id=wallet_message.message_id)
        await state.set_state(Expense.wallet)
        return query.message  # Возвращаем отредактированное сообщение как ключевое

    @date_router.message(Expense.date, CheckDateFilter())
    @track_messages
    async def set_date_text(message: Message, state: FSMContext, bot: Bot) -> Message:
        date = message.text
        await state.update_data(date=date)

        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)

        # Редактируем последнее сообщение бота
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

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, message.chat.id)

        # Отправляем новое сообщение для выбора кошелька
        wallet_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Выберите кошелёк для расходов: 💸",
            reply_markup=create_wallet_keyboard()
        )
        await state.update_data(wallet_message_id=wallet_message.message_id)
        await state.set_state(Expense.wallet)
        return message  # Возвращаем сообщение как индикатор завершения

    @date_router.message(Expense.date)
    @track_messages
    async def invalid_date_format(message: Message, state: FSMContext, bot: Bot) -> Message:
        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, message.chat.id)

        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Дата должна быть в формате дд.мм.гг или дд.мм.гггг. Повторите: 🗓️",
            reply_markup=create_today_keyboard()
        )
        await state.update_data(date_message_id=sent_message.message_id)
        await state.set_state(Expense.date)
        return sent_message

    return date_router