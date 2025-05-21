from aiogram import Router, Bot, html
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .state_income import Income
from ..delete_router import check_task_status
from ...api_client import ApiClient, IncomeIn
from ...keyboards.delete import create_delete_operation_kb
from ...keyboards.utils import ConfirmOperationCallback
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages, delete_key_messages

logger = configure_logger("[CONFIRM]", "green")


def create_confirm_router(bot: Bot, api_client: ApiClient):
    confirm_router = Router()

    @confirm_router.callback_query(Income.confirm, ConfirmOperationCallback.filter())
    @track_messages
    async def confirm_operation(query: CallbackQuery, callback_data: ConfirmOperationCallback, state: FSMContext,
                                bot: Bot) -> None:
        await query.answer()  # Явный ответ на callback
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        logger.debug(f"Callback data received: {callback_data.__dict__}")
        data = await state.get_data()
        operation_info = await format_income_message(data, api_client)

        if callback_data.confirm:
            logger.info(f"Пользователь {user_id} подтвердил операцию дохода")
            try:
                income = IncomeIn(
                    date=data.get("date"),
                    cat_code=data.get("category_code"),
                    amount=float(data.get("amount")),
                    comment=data.get("comment")
                )
                response = await api_client.add_income(income)
                if not response.ok or not response.task_id:
                    raise ValueError(f"Failed to add income: {response.detail or 'No task_id'}")

                task_id = response.task_id
                if await check_task_status(api_client, task_id):
                    await state.update_data(task_ids=[task_id], operation_message_text=operation_info)
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"{operation_info}\n\n✅ Доход успешно добавлен",
                        reply_markup=create_delete_operation_kb([task_id], confirm=False),
                        parse_mode=ParseMode.HTML
                    )
                    await state.set_state(Income.delete_income)
                else:
                    raise ValueError("Task timed out or failed")

            except Exception as e:
                logger.error(f"Ошибка при добавлении дохода для пользователя {user_id}: {e}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{operation_info}\n\n❌ Ошибка: {e}",
                    parse_mode=ParseMode.HTML
                )
        else:
            logger.info(f"Пользователь {user_id} отменил операцию дохода")
            await delete_tracked_messages(bot, state, chat_id, exclude_message_id=message_id)
            await delete_key_messages(bot, state, chat_id, exclude_message_id=message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{operation_info}\n\n🚫 Операция отменена",
                parse_mode=ParseMode.HTML
            )
            await state.clear()

    async def format_income_message(data: dict, api_client: ApiClient) -> str:
        date = data.get("date", "")
        category_code = data.get("category_code", "")
        amount = data.get("amount", 0)
        comment = data.get("comment", "")

        category_name = ""
        try:
            if category_code:
                categories = await api_client.get_incomes()
                category_name = next((cat.name for cat in categories if cat.code == category_code), category_code)
            logger.debug(f"Retrieved category name: {category_name}")
        except Exception as e:
            logger.warning(f"Error retrieving category name: {e}")

        message_lines = []
        if date:
            message_lines.append(f"Дата: 🗓️ {html.code(date)}")
        if category_name:
            message_lines.append(f"Категория: 🏷️ {html.code(category_name)}")
        if amount:
            message_lines.append(f"Сумма: 💰 {html.code(amount)} ₽")
        if comment:
            message_lines.append(f"Комментарий: 💬 {html.code(comment)}")

        return "\n".join(message_lines)

    return confirm_router
