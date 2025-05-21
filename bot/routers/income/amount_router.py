from aiogram import Router, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .state_income import Income
from ...api_client import ApiClient
from ...filters.check_amount import CheckAmountFilter
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_message, delete_tracked_messages

logger = configure_logger("[AMOUNT]", "orange")

def create_amount_router(bot: Bot, api_client: ApiClient):
    amount_router = Router()

    @amount_router.message(Income.amount, CheckAmountFilter())
    @track_messages
    async def set_amount(message: Message, state: FSMContext, bot: Bot) -> Message:
        amount = float(message.text.replace(',', '.'))
        await state.update_data(amount=amount)

        await delete_message(bot, message.chat.id, message.message_id)
        await delete_tracked_messages(bot, state, message.chat.id)

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

        comment_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Введите комментарий: 💬"
        )
        await state.update_data(comment_message_id=comment_message.message_id)
        await state.set_state(Income.comment)

        return amount_message

    @amount_router.message(Income.amount)
    @track_messages
    async def incorrect_amount(message: Message, state: FSMContext, bot: Bot) -> Message:
        await delete_message(bot, message.chat.id, message.message_id)
        await delete_tracked_messages(bot, state, message.chat.id)
        sent_message = await bot.send_message(
            chat_id=message.chat.id,
            text="Недопустимая сумма. Введите число больше 0 (разделитель: запятая). Попробуйте снова: 💰"
        )
        await state.update_data(amount_message_id=sent_message.message_id)
        await state.set_state(Income.amount)
        return sent_message

    return amount_router