# Bot/routers/income/comment_router.py
import asyncio
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from loguru import logger

from ..income.state_classes import Income
from ...api_client import ApiClient, IncomeIn
from ...keyboards.delete import create_delete_operation_kb, DeleteOperationCallback, ConfirmDeleteOperationCallback
from ...keyboards.start_kb import create_start_kb
from ...utils.message_utils import delete_messages_after, track_message


async def check_task_status(api_client: ApiClient, task_id: str, max_attempts: int = 10, delay: float = 2.0) -> bool:
    """Проверяет статус задачи до завершения или превышения попыток."""
    for attempt in range(max_attempts):
        status = await api_client.get_task_status(task_id)
        if status.get("status") == "completed":
            logger.info(f"Task {task_id} completed successfully")
            return True
        elif status.get("status") in ["failed", "error"]:
            logger.error(f"Task {task_id} failed: {status.get('error', 'Unknown error')}")
            return False
        logger.debug(f"Task {task_id} still pending, attempt {attempt + 1}/{max_attempts}")
        await asyncio.sleep(delay)
    logger.warning(f"Task {task_id} timed out after {max_attempts} attempts")
    return False


async def send_success_message(bot: Bot, chat_id: int, message_id: int, text: str, task_id: str) -> None:
    """Отправляет сообщение об успешной операции."""
    logger.info(f"Sending success message for task {task_id} to chat {chat_id}")
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=create_delete_operation_kb(task_id, False)
    )


def create_comment_router(bot: Bot, api_client: ApiClient):
    comment_router = Router()

    @comment_router.message(Income.comment, Command("skip"))
    @delete_messages_after
    @track_message
    async def skip_comment(message: Message, state: FSMContext):
        await set_comment(message, state, comment=None)

    @comment_router.message(Income.comment)
    @delete_messages_after
    @track_message
    async def set_comment(message: Message, state: FSMContext, comment: str | None = None):
        if comment is None:
            comment = message.text
        data = await state.get_data()
        await state.clear()

        logger.info(f"Processing income comment from user {message.from_user.id}: {comment or 'None'}")

        chat_id = message.chat.id
        comment_message_id = data.get("comment_message_id")
        date = data["date"]
        amount = data["amount"]
        category_code = data["category_code"]
        category_name = await api_client.get_category_name(data["chapter_code"], category_code)

        await message.delete()

        processing_message = await bot.edit_message_text(
            chat_id=chat_id,
            message_id=comment_message_id,
            text="Обрабатывается..."
        )
        logger.debug(f"Sent processing message to chat {chat_id}")

        try:
            date_obj = datetime.strptime(date, '%d.%m.%y' if len(date) == 8 else '%d.%m.%Y')
            formatted_date = date_obj.strftime('%d.%m.%Y')

            income = IncomeIn(
                date=formatted_date,
                amount=amount,
                category_code=category_code,
                comment=comment
            )
            response = await api_client.add_income(income)
            task_id = response.task_id
            logger.debug(f"Added income with task_id {task_id}")

            if await check_task_status(api_client, task_id):
                await send_success_message(
                    bot, chat_id, processing_message.message_id,
                    f"<b>✨ Приход успешно добавлен</b>\n"
                    f"Дата: <code>{formatted_date}</code>\n"
                    f"Категория: <code>{category_name}</code>\n"
                    f"Сумма: <code>{amount}</code> ₽\n"
                    f"Комментарий: <code>{comment or 'Нет'}</code>\n",
                    task_id
                )
            else:
                logger.error(f"Failed to add income for task {task_id}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=processing_message.message_id,
                    text="Ошибка при добавлении прихода. Попробуйте снова."
                )

        except Exception as e:
            logger.error(f"Error processing income operation: {e}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_message.message_id,
                text="Произошла ошибка. Попробуйте снова."
            )

        start_message = await bot.send_message(
            chat_id=chat_id,
            text="Выберите следующую операцию:",
            reply_markup=create_start_kb()
        )
        logger.debug(f"Sent start message to chat {chat_id}")
        return start_message

    @comment_router.callback_query(Income.delete_income, DeleteOperationCallback.filter(F.delete == True))
    @delete_messages_after
    @track_message
    async def confirm_delete_income(query: CallbackQuery, callback_data: DeleteOperationCallback):
        task_id = callback_data.operation_id
        logger.info(f"Confirming delete for income task {task_id} by user {query.from_user.id}")
        await query.message.edit_reply_markup(reply_markup=create_delete_operation_kb(task_id, True))
        await state.set_state(Income.delete_income)
        return query.message

    @comment_router.callback_query(Income.delete_income,
                                   ConfirmDeleteOperationCallback.filter(F.confirm_delete == True))
    @delete_messages_after
    @track_message
    async def delete_income(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback, state: FSMContext):
        task_id = callback_data.operation_id
        message_text = query.message.text
        logger.info(f"Deleting income task {task_id} by user {query.from_user.id}")

        await query.message.edit_text(text="Идет процесс удаления записи...\n\n" + message_text, reply_markup=None)

        try:
            response = await api_client.remove_income(task_id)
            task_ids = [response.task_id]
            logger.debug(f"Removing income with task_id {task_ids[0]}")

            if all(await check_task_status(api_client, tid) for tid in task_ids if tid):
                logger.info(f"Successfully deleted income tasks {task_ids}")
                final_message = await query.message.edit_text("*** Удалено ***\n\n" + message_text)
            else:
                logger.error(f"Failed to delete income tasks {task_ids}")
                final_message = await query.message.edit_text(
                    "Ошибка при удалении записи. Попробуйте снова.\n\n" + message_text)
        except Exception as e:
            logger.error(f"Error deleting income operation: {e}")
            final_message = await query.message.edit_text(
                "Произошла ошибка при удалении. Попробуйте снова.\n\n" + message_text)

        await state.clear()
        return final_message

    @comment_router.callback_query(Income.delete_income,
                                   ConfirmDeleteOperationCallback.filter(F.confirm_delete == False))
    @delete_messages_after
    @track_message
    async def cancel_delete_income(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback,
                                   state: FSMContext):
        task_id = callback_data.operation_id
        logger.info(f"Cancelling delete for income task {task_id} by user {query.from_user.id}")
        await query.message.edit_reply_markup(
            reply_markup=create_delete_operation_kb(task_id, False)
        )
        await state.clear()
        return query.message

    return comment_router
