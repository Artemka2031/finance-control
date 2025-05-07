from aiogram import Router, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from ..expenses.state_classes import Expense
from ...api_client import ApiClient
from ...filters.check_amount import CheckAmountFilter
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_message, delete_tracked_messages

logger = configure_logger("[AMOUNT]", "orange")

def create_amount_router(bot: Bot, api_client: ApiClient):
    amount_router = Router()

    @amount_router.message(Expense.amount, CheckAmountFilter())
    @track_messages
    async def set_amount(message: Message, state: FSMContext, bot: Bot) -> Message:
        amount = float(message.text.replace(',', '.'))
        await state.update_data(amount=amount)

        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, message.chat.id)

        # Обновляем сообщение о сумме
        data = await state.get_data()
        amount_message_id = data.get("amount_message_id")
        amount_message = None
        if amount_message_id:
            try:
                amount_message = await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=amount_message_id,
                    text=f"Выбрана сумма: 💰 {html.bold(amount)} ₽",
                    reply_markup=None
                )
                logger.debug(f"Отредактировано сообщение {amount_message_id} с суммой {amount}")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {amount_message_id}: {e}")
                amount_message = await bot.send_message(
                    chat_id=message.chat.id,
                    text=f"Выбрана сумма: 💰 {html.bold(amount)} ₽",
                    reply_markup=None
                )
                amount_message_id = amount_message.message_id
                await state.update_data(amount_message_id=amount_message_id)
                logger.debug(f"Отправлено новое сообщение {amount_message_id} с суммой {amount}")

        wallet = data.get("wallet")
        if wallet == "borrow":
            # Создаём клавиатуру с коэффициентом по умолчанию
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Коэффициент по умолчанию (1.0)", callback_data="COEF:1.0")]
            ])
            saving_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Введите коэффициент экономии или выберите по умолчанию: 📊",
                reply_markup=keyboard
            )
            await state.update_data(coefficient_message_id=saving_message.message_id)
            await state.set_state(Expense.coefficient)
        else:
            comment_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Введите комментарий: 💬"
            )
            await state.update_data(comment_message_id=comment_message.message_id)
            await state.set_state(Expense.comment)

        # Возвращаем отредактированное сообщение о сумме
        return amount_message

    @amount_router.callback_query(Expense.coefficient, lambda c: c.data.startswith("COEF:"))
    @track_messages
    async def set_default_coefficient(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        coefficient = float(query.data.split(":")[1])
        await state.update_data(coefficient=coefficient)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, query.message.chat.id)

        # Обновляем сообщение о коэффициенте
        data = await state.get_data()
        coefficient_message_id = data.get("coefficient_message_id")
        coefficient_message = None
        if coefficient_message_id:
            try:
                coefficient_message = await bot.edit_message_text(
                    chat_id=query.message.chat.id,
                    message_id=coefficient_message_id,
                    text=f"Выбран коэффициент экономии: 📊 {html.bold(coefficient)}",
                    reply_markup=None
                )
                logger.debug(f"Отредактировано сообщение {coefficient_message_id} с коэффициентом {coefficient}")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {coefficient_message_id}: {e}")
                coefficient_message = await bot.send_message(
                    chat_id=query.message.chat.id,
                    text=f"Выбран коэффициент экономии: 📊 {html.bold(coefficient)}",
                    reply_markup=None
                )
                await state.update_data(coefficient_message_id=coefficient_message.message_id)
                logger.debug(
                    f"Отправлено новое сообщение {coefficient_message.message_id} с коэффициентом {coefficient}")

        comment_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text="Введите комментарий: 💬"
        )
        await state.update_data(comment_message_id=comment_message.message_id)
        await state.set_state(Expense.comment)
        return coefficient_message

    @amount_router.message(Expense.coefficient)
    @track_messages
    async def set_coefficient(message: Message, state: FSMContext, bot: Bot) -> Message:
        try:
            coefficient = float(message.text.replace(',', '.'))
            if coefficient <= 0:
                raise ValueError("Коэффициент должен быть больше 0")
        except ValueError:
            # Удаляем сообщение пользователя
            await delete_message(bot, message.chat.id, message.message_id)
            # Удаляем временные сообщения
            await delete_tracked_messages(bot, state, message.chat.id)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Коэффициент по умолчанию (1.0)", callback_data="COEF:1.0")]
            ])
            sent_message = await bot.send_message(
                chat_id=message.chat.id,
                text="Недопустимый коэффициент. Введите число больше 0 (разделитель: запятая). Попробуйте снова: 📊",
                reply_markup=keyboard
            )
            await state.update_data(coefficient_message_id=sent_message.message_id)
            await state.set_state(Expense.coefficient)
            return sent_message

        await state.update_data(coefficient=coefficient)

        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, message.chat.id)

        # Обновляем сообщение о коэффициенте
        data = await state.get_data()
        coefficient_message_id = data.get("coefficient_message_id")
        coefficient_message = None
        if coefficient_message_id:
            try:
                coefficient_message = await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=coefficient_message_id,
                    text=f"Выбран коэффициент экономии: 📊 {html.bold(coefficient)}",
                    reply_markup=None
                )
                logger.debug(f"Отредактировано сообщение {coefficient_message_id} с коэффициентом {coefficient}")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {coefficient_message_id}: {e}")
                coefficient_message = await bot.send_message(
                    chat_id=message.chat.id,
                    text=f"Выбран коэффициент экономии: 📊 {html.bold(coefficient)}",
                    reply_markup=None
                )
                await state.update_data(coefficient_message_id=coefficient_message.message_id)
                logger.debug(
                    f"Отправлено новое сообщение {coefficient_message.message_id} с коэффициентом {coefficient}")

        comment_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Введите комментарий: 💬"
        )
        await state.update_data(comment_message_id=comment_message.message_id)
        await state.set_state(Expense.comment)
        return coefficient_message

    @amount_router.message(Expense.amount)
    @track_messages
    async def incorrect_amount(message: Message, state: FSMContext, bot: Bot) -> Message:
        # Удаляем сообщение пользователя
        await delete_message(bot, message.chat.id, message.message_id)
        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, message.chat.id)
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Недопустимая сумма. Введите число больше 0 (разделитель: запятая). Попробуйте снова: 💰"
        )
        await state.update_data(amount_message_id=sent_message.message_id)
        await state.set_state(Expense.amount)
        return sent_message

    return amount_router