from aiogram import Router, F, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup

from api_client import ApiClient
from keyboards.income_category import ChooseIncomeCategoryCallback
from routers.income.state_income import Income
from utils.logging import configure_logger
from utils.message_utils import track_messages

logger = configure_logger("[CATEGORY]", "purple")


def create_category_router(bot: Bot, api_client: ApiClient):
    category_router = Router()

    async def update_status_message(chat_id: int, state: FSMContext, bot: Bot, message_id: int = None,
                                    keyboard: InlineKeyboardMarkup = None) -> None:
        data = await state.get_data()
        status_message_id = data.get("category_message_id")
        category_name = data.get("category_name", "Не выбрано")

        text = f"Категория: {html.bold(category_name)}"

        try:
            if message_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                if message_id != status_message_id:
                    await state.update_data(category_message_id=message_id)
                logger.debug(f"Создано/обновлено сообщение {message_id} в чате {chat_id}")
            else:
                new_message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                await state.update_data(category_message_id=new_message.message_id)
                logger.debug(f"Создано новое сообщение {new_message.message_id} в чате {chat_id}")
        except Exception as e:
            logger.warning(f"Не удалось обновить сообщение в чате {chat_id}: {e}")
            new_message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.update_data(category_message_id=new_message.message_id)
            logger.debug(f"Создано новое сообщение {new_message.message_id} в чате {chat_id}")

    @category_router.callback_query(Income.category_code, ChooseIncomeCategoryCallback.filter(F.back == False))
    @track_messages
    async def set_category(query: CallbackQuery, state: FSMContext, bot: Bot,
                           callback_data: ChooseIncomeCategoryCallback) -> Message:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        category_code = callback_data.category_code

        logger.info(f"Пользователь {user_id} выбрал категорию '{category_code}'")

        categories = await api_client.get_incomes()
        category_name = next((cat.name for cat in categories if cat.code == category_code), category_code)
        await state.update_data(category_code=category_code, category_name=category_name)

        await update_status_message(chat_id, state, bot, message_id)

        amount_message = await bot.send_message(
            chat_id=chat_id,
            text="Введите сумму дохода: 💰"
        )
        await state.update_data(amount_message_id=amount_message.message_id)
        await state.set_state(Income.amount)
        logger.info(f"Переход в состояние Income.amount, отправлено сообщение {amount_message.message_id}")
        return query.message

    return category_router
