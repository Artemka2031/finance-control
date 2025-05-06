# Bot/routers/expenses/comment_router.py
import asyncio
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ..expenses.state_classes import Expense
from ...api_client import ApiClient, ExpenseIn, CreditorIn
from ...keyboards.delete import create_delete_operation_kb, DeleteOperationCallback, ConfirmDeleteOperationCallback
from ...keyboards.start_kb import create_start_kb
from ...utils.logging import configure_logger
from ...utils.message_utils import delete_messages_after, track_message

# Configure logger
logger = configure_logger("[EXPENSES]", "yellow")

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

async def get_category_name(api_client: ApiClient, chapter_code: str, category_code: str, subcategory_code: str) -> str:
    """Получает имя категории или подкатегории."""
    if subcategory_code:
        subcategories = await api_client.get_subcategories(chapter_code, category_code)
        name = next((sub.name for sub in subcategories if sub.code == subcategory_code), "")
        logger.debug(f"Retrieved subcategory name: {name}")
        return name
    if category_code:
        categories = await api_client.get_categories(chapter_code)
        name = next((cat.name for cat in categories if cat.code == category_code), "")
        logger.debug(f"Retrieved category name: {name}")
        return name
    logger.debug("No category or subcategory specified")
    return ""


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

    @comment_router.message(Expense.comment)
    @delete_messages_after
    @track_message
    async def set_comment(message: Message, state: FSMContext, bot: Bot) -> Message:
        comment = message.text
        data = await state.get_data()
        await state.clear()

        logger.info(f"Processing expense comment from user {message.from_user.id}: {comment}")

        date_obj = datetime.strptime(data["date"], '%d.%m.%y' if len(data["date"]) == 8 else '%d.%m.%Y')
        date = date_obj.strftime('%d.%m.%Y')
        amount = data["amount"]
        wallet = data["wallet"]
        chat_id = message.chat.id

        processing_message = await bot.send_message(chat_id=chat_id, text="Обрабатывается...")
        logger.debug(f"Sent processing message to chat {chat_id}")

        try:
            if wallet == "project":
                chapter_code = data["chapter_code"]
                category_code = data.get("category_code", "")
                subcategory_code = data.get("subcategory_code", "")

                expense = ExpenseIn(
                    date=date,
                    amount=amount,
                    section_code=chapter_code,
                    category_code=category_code,
                    subcategory_code=subcategory_code,
                    comment=comment
                )
                response = await api_client.add_expense(expense)
                task_id = response.task_id
                logger.debug(f"Added expense with task_id {task_id}")

                category_name = await get_category_name(api_client, chapter_code, category_code, subcategory_code)

                if await check_task_status(api_client, task_id):
                    await send_success_message(
                        bot, chat_id, processing_message.message_id,
                        f"<b>✨ Расход успешно добавлен</b>\n"
                        f"Дата: <code>{date}</code>\n"
                        f"Категория: <code>{category_name}</code>\n"
                        f"Сумма: <code>{amount}</code> ₽\n"
                        f"Комментарий: <code>{comment}</code>\n",
                        task_id
                    )
                else:
                    logger.error(f"Failed to add expense for task {task_id}")
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=processing_message.message_id,
                        text="Ошибка при добавлении расхода. Попробуйте снова."
                    )

            elif wallet == "borrow":
                chapter_code = data["chapter_code"]
                category_code = data.get("category_code", "")
                subcategory_code = data.get("subcategory_code", "")
                coefficient = data.get("coefficient", 1.0)
                creditor = data["creditor"]

                borrowing_amount = round(amount * coefficient)
                saving_amount = round(amount * (1 - coefficient)) if coefficient != 1 else 0

                expense = ExpenseIn(
                    date=date,
                    amount=borrowing_amount,
                    section_code=chapter_code,
                    category_code=category_code,
                    subcategory_code=subcategory_code,
                    comment=comment
                )
                borrowing = CreditorIn(
                    date=date,
                    amount=borrowing_amount,
                    creditor_code=creditor,
                    comment=comment
                )
                response_expense = await api_client.add_expense(expense)
                response_borrowing = await api_client.record_borrowing(borrowing)
                task_ids = [response_expense.task_id, response_borrowing.task_id]
                logger.debug(f"Added expense and borrowing with task_ids {task_ids}")

                if saving_amount > 0:
                    saving = CreditorIn(
                        date=date,
                        amount=saving_amount,
                        creditor_code=creditor,
                        comment=comment
                    )
                    response_saving = await api_client.record_saving(saving)
                    task_ids.append(response_saving.task_id)
                    logger.debug(f"Added saving with task_id {response_saving.task_id}")

                category_name = await get_category_name(api_client, chapter_code, category_code, subcategory_code)

                if all(await check_task_status(api_client, task_id) for task_id in task_ids):
                    await send_success_message(
                        bot, chat_id, processing_message.message_id,
                        f"<b>✨ Записан долг и расход</b>\n"
                        f"Дата: <code>{date}</code>\n"
                        f"Категория: <code>{category_name}</code>\n"
                        f"Кредитор: <code>{creditor}</code>\n"
                        f"Коэффициент: <code>{coefficient}</code>\n"
                        f"Взятая сумма: <code>{borrowing_amount}</code> ₽\n"
                        f"Экономия: <code>{saving_amount}</code> ₽\n"
                        f"Общий расход: <code>{amount}</code> ₽\n"
                        f"Комментарий: <code>{comment}</code>\n",
                        task_ids[0]  # Use expense task_id
                    )
                else:
                    logger.error(f"Failed to add borrowing/expense for task_ids {task_ids}")
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=processing_message.message_id,
                        text="Ошибка при добавлении долга и расхода. Попробуйте снова."
                    )

            elif wallet == "repay":
                creditor = data["creditor"]
                repayment = CreditorIn(
                    date=date,
                    amount=amount,
                    creditor_code=creditor,
                    comment=comment
                )
                response = await api_client.record_repayment(repayment)
                task_id = response.task_id
                logger.debug(f"Recorded repayment with task_id {task_id}")

                if await check_task_status(api_client, task_id):
                    await send_success_message(
                        bot, chat_id, processing_message.message_id,
                        f"<b>✨ Возврат долга</b>\n"
                        f"Дата: <code>{date}</code>\n"
                        f"Кредитор: <code>{creditor}</code>\n"
                        f"Сумма: <code>{amount}</code> ₽\n"
                        f"Комментарий: <code>{comment}</code>\n",
                        task_id
                    )
                else:
                    logger.error(f"Failed to record repayment for task {task_id}")
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=processing_message.message_id,
                        text="Ошибка при возврате долга. Попробуйте снова."
                    )

            elif wallet == "dividends":
                chapter_code = data["chapter_code"]
                category_code = data.get("category_code", "")
                subcategory_code = data.get("subcategory_code", "")

                expense = ExpenseIn(
                    date=date,
                    amount=amount,
                    section_code=chapter_code,
                    category_code=category_code,
                    subcategory_code=subcategory_code,
                    comment=comment
                )
                response = await api_client.add_expense(expense)
                task_id = response.task_id
                logger.debug(f"Added dividends expense with task_id {task_id}")

                category_name = await get_category_name(api_client, chapter_code, category_code, subcategory_code)

                if await check_task_status(api_client, task_id):
                    await send_success_message(
                        bot, chat_id, processing_message.message_id,
                        f"<b>✨ Расход (Дивиденды) успешно добавлен</b>\n"
                        f"Дата: <code>{date}</code>\n"
                        f"Категория: <code>{category_name}</code>\n"
                        f"Сумма: <code>{amount}</code> ₽\n"
                        f"Комментарий: <code>{comment}</code>\n",
                        task_id
                    )
                else:
                    logger.error(f"Failed to add dividends expense for task {task_id}")
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=processing_message.message_id,
                        text="Ошибка при добавлении расхода (Дивиденды). Попробуйте снова."
                    )

        except Exception as e:
            logger.error(f"Error processing expense operation: {e}")
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

    @comment_router.callback_query(Expense.delete_expense, DeleteOperationCallback.filter(F.delete == True))
    @delete_messages_after
    @track_message
    async def confirm_delete_expense(query: CallbackQuery, callback_data: DeleteOperationCallback, state: FSMContext,
                                     bot: Bot) -> Message:
        task_id = callback_data.operation_id
        logger.info(f"Confirming delete for expense task {task_id} by user {query.from_user.id}")
        await query.message.edit_reply_markup(reply_markup=create_delete_operation_kb(task_id, True))
        await state.set_state(Expense.delete_expense)
        return query.message

    @comment_router.callback_query(Expense.delete_expense,
                                   ConfirmDeleteOperationCallback.filter(F.confirm_delete == True))
    @delete_messages_after
    @track_message
    async def delete_expense(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback, state: FSMContext,
                             bot: Bot) -> Message:
        task_id = callback_data.operation_id
        message_text = query.message.text
        logger.info(f"Deleting expense task {task_id} by user {query.from_user.id}")

        await query.message.edit_text(text="Идет процесс удаления записи...\n\n" + message_text, reply_markup=None)

        try:
            if "Записан долг и расход" in message_text:
                response_expense = await api_client.remove_expense(task_id)
                response_borrowing = await api_client.remove_borrowing(task_id)
                response_saving = await api_client.remove_saving(task_id)
                task_ids = [response_expense.task_id, response_borrowing.task_id, response_saving.task_id]
                logger.debug(f"Removing expense, borrowing, and saving with task_ids {task_ids}")
            elif "Возврат долга" in message_text:
                response = await api_client.remove_repayment(task_id)
                task_ids = [response.task_id]
                logger.debug(f"Removing repayment with task_id {task_ids[0]}")
            else:
                response = await api_client.remove_expense(task_id)
                task_ids = [response.task_id]
                logger.debug(f"Removing expense with task_id {task_ids[0]}")

            if all(await check_task_status(api_client, tid) for tid in task_ids if tid):
                logger.info(f"Successfully deleted expense tasks {task_ids}")
                final_message = await bot.edit_message_text(
                    chat_id=query.message.chat.id,
                    message_id=query.message.message_id,
                    text="*** Удалено ***\n\n" + message_text
                )
            else:
                logger.error(f"Failed to delete expense tasks {task_ids}")
                final_message = await bot.edit_message_text(
                    chat_id=query.message.chat.id,
                    message_id=query.message.message_id,
                    text="Ошибка при удалении записи. Попробуйте снова.\n\n" + message_text
                )
        except Exception as e:
            logger.error(f"Error deleting expense operation: {e}")
            final_message = await bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=query.message.message_id,
                text="Произошла ошибка при удалении. Попробуйте снова.\n\n" + message_text
            )

        await state.clear()
        return final_message

    @comment_router.callback_query(Expense.delete_expense,
                                   ConfirmDeleteOperationCallback.filter(F.confirm_delete == False))
    @delete_messages_after
    @track_message
    async def cancel_delete_expense(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback,
                                    state: FSMContext, bot: Bot) -> Message:
        task_id = callback_data.operation_id
        logger.info(f"Cancelling delete for expense task {task_id} by user {query.from_user.id}")
        await query.message.edit_reply_markup(
            reply_markup=create_delete_operation_kb(task_id, False)
        )
        await state.clear()
        return query.message

    return comment_router