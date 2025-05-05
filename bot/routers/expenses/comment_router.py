import asyncio
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.api_client import ApiClient, ExpenseIn, CreditorIn
from bot.keyboards.delete import create_delete_operation_kb
from bot.keyboards.start_kb import create_start_kb
from bot.keyboards.utils import DeleteOperationCallback, ConfirmDeleteOperationCallback
from bot.routers.expenses.state_classes import Expense
from bot.utils.message_utils import delete_messages_after, track_message


async def check_task_status(api_client: ApiClient, task_id: str, max_attempts: int = 10, delay: float = 2.0) -> bool:
    """Проверяет статус задачи до завершения или превышения попыток."""
    for _ in range(max_attempts):
        status = await api_client.get_task_status(task_id)
        if status.get("status") == "completed":
            return True
        elif status.get("status") in ["failed", "error"]:
            logging.error(f"Task {task_id} failed: {status.get('error', 'Unknown error')}")
            return False
        await asyncio.sleep(delay)
    logging.warning(f"Task {task_id} timed out after {max_attempts} attempts")
    return False


async def get_category_name(api_client: ApiClient, chapter_code: str, category_code: str, subcategory_code: str) -> str:
    """Получает имя категории или подкатегории."""
    if subcategory_code:
        subcategories = await api_client.get_subcategories(chapter_code, category_code)
        return next((sub.name for sub in subcategories if sub.code == subcategory_code), "")
    if category_code:
        categories = await api_client.get_categories(chapter_code)
        return next((cat.name for cat in categories if cat.code == category_code), "")
    return ""


async def send_success_message(bot, chat_id: int, message_id: int, text: str, task_id: str) -> None:
    """Отправляет сообщение об успешной операции."""
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=create_delete_operation_kb(task_id, False)
    )


def create_comment_router(bot, api_client: ApiClient):
    comment_router = Router()

    @comment_router.message(Expense.comment)
    @delete_messages_after
    @track_message
    async def set_comment(message: Message, state: FSMContext) -> Message:
        comment = message.text
        data = await state.get_data()
        await state.clear()

        date_obj = datetime.strptime(data["date"], '%d.%m.%y' if len(data["date"]) == 8 else '%d.%m.%Y')
        date = date_obj.strftime('%d.%m.%Y')
        amount = data["amount"]
        wallet = data["wallet"]
        chat_id = message.chat.id

        processing_message = await bot.send_message(chat_id=chat_id, text="Обрабатывается...")

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

                if saving_amount > 0:
                    saving = CreditorIn(
                        date=date,
                        amount=saving_amount,
                        creditor_code=creditor,
                        comment=comment
                    )
                    response_saving = await api_client.record_saving(saving)
                    task_ids.append(response_saving.task_id)

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
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=processing_message.message_id,
                        text="Ошибка при добавлении расхода (Дивиденды). Попробуйте снова."
                    )

        except Exception as e:
            logging.error(f"Error processing operation: {e}")
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
        return start_message

    @comment_router.callback_query(DeleteOperationCallback.filter(F.delete == True))
    @delete_messages_after
    @track_message
    async def confirm_delete_expense(query: CallbackQuery, callback_data: DeleteOperationCallback) -> Message:
        task_id = callback_data.operation_id
        await query.message.edit_reply_markup(reply_markup=create_delete_operation_kb(task_id, True))
        return query.message

    @comment_router.callback_query(ConfirmDeleteOperationCallback.filter(F.confirm_delete == True))
    @delete_messages_after
    @track_message
    async def delete_expense(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback) -> Message:
        task_id = callback_data.operation_id
        message_text = query.message.text

        await query.message.edit_text(text="Идет процесс удаления записи...\n\n" + message_text, reply_markup=None)

        try:
            if "Записан долг и расход" in message_text:
                response_expense = await api_client.remove_expense(task_id)
                response_borrowing = await api_client.remove_borrowing(task_id)
                response_saving = await api_client.remove_saving(task_id)
                task_ids = [response_expense.task_id, response_borrowing.task_id, response_saving.task_id]
            elif "Возврат долга" in message_text:
                response = await api_client.remove_repayment(task_id)
                task_ids = [response.task_id]
            else:
                response = await api_client.remove_expense(task_id)
                task_ids = [response.task_id]

            if all(await check_task_status(api_client, tid) for tid in task_ids if tid):
                final_message = await query.message.edit_text("*** Удалено ***\n\n" + message_text)
            else:
                final_message = await query.message.edit_text(
                    "Ошибка при удалении записи. Попробуйте снова.\n\n" + message_text)
        except Exception as e:
            logging.error(f"Error deleting operation: {e}")
            final_message = await query.message.edit_text(
                "Произошла ошибка при удалении. Попробуйте снова.\n\n" + message_text)

        return final_message

    @comment_router.callback_query(ConfirmDeleteOperationCallback.filter(F.confirm_delete == False))
    @delete_messages_after
    @track_message
    async def cancel_delete_expense(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback) -> Message:
        task_id = callback_data.operation_id
        await query.message.edit_reply_markup(
            reply_markup=create_delete_operation_kb(task_id, False)
        )
        return query.message

    return comment_router
