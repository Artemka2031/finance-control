import asyncio
from aiogram import Router, Bot, html, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .state_income import Income
from ...api_client import ApiClient, IncomeIn
from ...keyboards.delete import create_delete_operation_kb
from ...keyboards.start_kb import create_start_kb
from ...keyboards.utils import ConfirmOperationCallback
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages, delete_key_messages, format_income_message, \
    check_task_status, animate_processing, send_success_message

logger = configure_logger("[CONFIRM]", "green")


def create_confirm_router(bot: Bot, api_client: ApiClient):
    confirm_router = Router()

    @confirm_router.callback_query(Income.confirm, ConfirmOperationCallback.filter(F.confirm == True))
    @track_messages
    async def confirm_operation(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        await query.answer()
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        data = await state.get_data()
        operation_info = await format_income_message(data, api_client)

        logger.info(f"Пользователь {user_id} подтвердил операцию дохода, message_id={message_id}")

        animation_task = asyncio.create_task(animate_processing(bot, chat_id, message_id, operation_info))

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
                animation_task.cancel()
                await delete_tracked_messages(bot, state, chat_id)
                await state.update_data(messages_to_delete=[])
                await send_success_message(
                    bot, chat_id, message_id,
                    f"{operation_info}\n\n✅ Доход успешно добавлен",
                    [task_id], state, operation_info
                )
                await state.set_state(Income.delete_income)
            else:
                raise ValueError("Task timed out or failed")

        except Exception as e:
            logger.error(f"Ошибка при добавлении дохода для пользователя {user_id}: {e}")
            animation_task.cancel()
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{operation_info}\n\n❌ Ошибка: {e}",
                parse_mode=ParseMode.HTML
            )

        data = await state.get_data()
        persistent_data = {
            "operation_message_text": data.get("operation_message_text"),
            "task_ids": data.get("task_ids")
        }
        await state.clear()
        await state.update_data(**persistent_data)

        start_message = await bot.send_message(
            chat_id=chat_id,
            text="Выберите следующую операцию: 🔄",
            reply_markup=create_start_kb()
        )
        return start_message

    @confirm_router.callback_query(Income.confirm, ConfirmOperationCallback.filter(F.confirm == False))
    @track_messages
    async def cancel_operation(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        await query.answer()
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        data = await state.get_data()
        operation_info = await format_income_message(data, api_client)

        logger.info(f"Пользователь {user_id} отменил операцию дохода, message_id={message_id}")

        await delete_tracked_messages(bot, state, chat_id)
        await delete_key_messages(bot, state, chat_id)
        await state.update_data(messages_to_delete=[])

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"Добавление дохода отменено:\n{operation_info} 🚫",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id}: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"Добавление дохода отменено:\n{operation_info} 🚫",
                parse_mode=ParseMode.HTML
            )

        await state.clear()
        start_message = await bot.send_message(
            chat_id=chat_id,
            text="Выберите следующую операцию: 🔄",
            reply_markup=create_start_kb()
        )
        return start_message

    return confirm_router
