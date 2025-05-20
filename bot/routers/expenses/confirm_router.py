import asyncio
from datetime import datetime

from aiogram import Router, Bot, html, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..expenses.state_classes import Expense
from ...api_client import ApiClient, ExpenseIn, CreditorIn
from ...keyboards.delete import create_delete_operation_kb
from ...keyboards.start_kb import create_start_kb
from ...keyboards.utils import ConfirmOperationCallback
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages, delete_key_messages, \
    format_operation_message

logger = configure_logger("[CONFIRM]", "blue")


async def check_task_status(api_client: ApiClient, task_id: str, max_attempts: int = 10, delay: float = 2.0) -> bool:
    for attempt in range(max_attempts):
        try:
            status = await api_client.get_task_status(task_id)
            if status.get("status") == "completed":
                logger.info(f"Task {task_id} completed successfully")
                return True
            elif status.get("status") in ["failed", "error"]:
                logger.error(f"Task {task_id} failed: {status.get('error', 'Unknown error')}")
                return False
        except Exception as e:
            logger.warning(f"Error checking task {task_id} status: {e}")
        logger.debug(f"Task {task_id} still pending, attempt {attempt + 1}/{max_attempts}")
        await asyncio.sleep(delay)
    logger.warning(f"Task {task_id} timed out after {max_attempts} attempts")
    return False


async def animate_processing(bot: Bot, chat_id: int, message_id: int, base_text: str) -> None:
    """Запускает анимацию обработки в отдельной задаче."""
    dots = [".", "..", "..."]
    while True:
        for dot in dots:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{base_text}\n\n⏳ Обрабатываем операцию{dot} ",
                    reply_markup=None,
                    parse_mode="HTML"
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Failed to animate processing for message {message_id}: {e}")
                return


async def send_success_message(bot: Bot, chat_id: int, message_id: int, text: str, task_ids: list[str],
                               state: FSMContext, operation_info: str) -> None:
    logger.info(f"Sending success message for tasks {task_ids} to chat {chat_id}")
    # Сохраняем чистый текст операции и валидные task_ids в состоянии
    valid_task_ids = [tid for tid in task_ids if tid is not None]
    if not valid_task_ids:
        logger.error(f"No valid task_ids provided: {task_ids}")
    await state.update_data(operation_message_text=operation_info, task_ids=valid_task_ids)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=create_delete_operation_kb(valid_task_ids, confirm=False),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Failed to edit success message {message_id}: {e}")
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=create_delete_operation_kb(valid_task_ids, confirm=False),
            parse_mode="HTML"
        )
        logger.debug(f"Sent new success message {sent_message.message_id}")


def create_confirm_router(bot: Bot, api_client: ApiClient):
    confirm_router = Router()

    @confirm_router.callback_query(Expense.confirm, ConfirmOperationCallback.filter(F.confirm == True))
    @track_messages
    async def confirm_operation(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        data = await state.get_data()

        logger.info(f"Пользователь {user_id} подтвердил операцию, message_id={message_id}")

        # Получаем исходное сообщение операции
        operation_info = await format_operation_message(data, api_client)

        # Запускаем анимацию обработки с исходным текстом
        animation_task = asyncio.create_task(animate_processing(bot, chat_id, message_id, operation_info))

        date = data.get("date", "Не выбрано")
        amount = data.get("amount", 0)
        wallet = data.get("wallet")
        wallet_name = data.get("wallet_name", wallet)
        comment = data.get("comment", "")
        task_ids = []

        try:
            date_obj = datetime.strptime(date, '%d.%m.%y' if len(date) == 8 else '%d.%m.%Y')
            date = date_obj.strftime('%d.%m.%Y')

            if wallet == "project":
                sec_code = data.get("chapter_code")
                cat_code = data.get("category_code", "")
                sub_code = data.get("subcategory_code", "")
                expense = ExpenseIn(
                    date=date,
                    sec_code=sec_code,
                    cat_code=cat_code,
                    sub_code=sub_code,
                    amount=amount,
                    comment=comment
                )
                try:
                    response = await api_client.add_expense(expense)
                    task_id = response.task_id
                    if not task_id:
                        raise ValueError("No task_id in response")
                    task_ids.append(task_id)
                except Exception as e:
                    logger.error(f"API error adding expense: {e}")
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при добавлении расхода:\n{operation_info}\n\n{e} ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                    return await bot.send_message(
                        chat_id=chat_id,
                        text="Выберите следующую операцию: 🔄",
                        reply_markup=create_start_kb()
                    )

                if await check_task_status(api_client, task_id):
                    animation_task.cancel()
                    await delete_tracked_messages(bot, state, chat_id)
                    await state.update_data(messages_to_delete=[])
                    await send_success_message(
                        bot, chat_id, message_id,
                        f"{html.bold('Расход успешно добавлен')} ✅\n{operation_info}",
                        task_ids, state, operation_info
                    )
                else:
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при добавлении расхода:\n{operation_info}\n\nТайм-аут сервера ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )

            elif wallet == "borrow":
                sec_code = data.get("chapter_code")
                cat_code = data.get("category_code", "")
                sub_code = data.get("subcategory_code", "")
                coefficient = data.get("coefficient", 1.0)
                creditor = data.get("creditor")
                creditor_name = data.get("creditor_name", creditor)
                borrowing_amount = amount
                saving_amount = round(amount * (1 - coefficient)) if coefficient != 1 else 0
                expense = ExpenseIn(
                    date=date,
                    sec_code=sec_code,
                    cat_code=cat_code,
                    sub_code=sub_code,
                    amount=borrowing_amount,
                    comment=comment
                )
                borrowing = CreditorIn(
                    date=date,
                    cred_code=creditor,
                    amount=borrowing_amount,
                    comment=comment
                )
                try:
                    response_expense = await api_client.add_expense(expense)
                    response_borrowing = await api_client.record_borrowing(borrowing)
                    task_ids.extend([response_expense.task_id, response_borrowing.task_id])
                    if not all(task_id for task_id in task_ids):
                        raise ValueError("Missing task_id in response")
                except Exception as e:
                    logger.error(f"API error adding expense/borrowing: {e}")
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при добавлении долга и расхода:\n{operation_info}\n\n{e} ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                    return await bot.send_message(
                        chat_id=chat_id,
                        text="Выберите следующую операцию: 🔄",
                        reply_markup=create_start_kb()
                    )

                if saving_amount > 0:
                    saving = CreditorIn(
                        date=date,
                        cred_code=creditor,
                        amount=saving_amount,
                        comment=comment
                    )
                    try:
                        response_saving = await api_client.record_saving(saving)
                        if response_saving.task_id:
                            task_ids.append(response_saving.task_id)
                        else:
                            logger.warning(f"No task_id for saving: {response_saving}")
                    except Exception as e:
                        logger.error(f"API error adding saving: {e}")

                # Check all task statuses concurrently
                task_results = await asyncio.gather(
                    *(check_task_status(api_client, task_id) for task_id in task_ids if task_id))
                if all(task_results):
                    animation_task.cancel()
                    await delete_tracked_messages(bot, state, chat_id)
                    await state.update_data(messages_to_delete=[])
                    await send_success_message(
                        bot, chat_id, message_id,
                        f"{html.bold('Записан долг и расход')} ✅\n{operation_info}",
                        task_ids, state, operation_info
                    )
                else:
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при добавлении долга и расхода:\n{operation_info}\n\nТайм-аут сервера или ошибка выполнения задач ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )

            elif wallet == "repay":
                creditor = data.get("creditor")
                creditor_name = data.get("creditor_name", creditor)
                repayment = CreditorIn(
                    date=date,
                    cred_code=creditor,
                    amount=amount,
                    comment=comment
                )
                try:
                    response = await api_client.record_repayment(repayment)
                    task_id = response.task_id
                    if not task_id:
                        raise ValueError("No task_id in response")
                    task_ids.append(task_id)
                except Exception as e:
                    logger.error(f"API error adding repayment: {e}")
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при возврате долга:\n{operation_info}\n\n{e} ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                    return await bot.send_message(
                        chat_id=chat_id,
                        text="Выберите следующую операцию: 🔄",
                        reply_markup=create_start_kb()
                    )

                if await check_task_status(api_client, task_id):
                    animation_task.cancel()
                    await delete_tracked_messages(bot, state, chat_id)
                    await state.update_data(messages_to_delete=[])
                    await send_success_message(
                        bot, chat_id, message_id,
                        f"{html.bold('Возврат долга')} ✅\n{operation_info}",
                        task_ids, state, operation_info
                    )
                else:
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при возврате долга:\n{operation_info}\n\nТайм-аут сервера ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )

            elif wallet == "dividends":
                sec_code = data.get("chapter_code")
                cat_code = data.get("category_code", "")
                sub_code = data.get("subcategory_code", "")
                expense = ExpenseIn(
                    date=date,
                    sec_code=sec_code,
                    cat_code=cat_code,
                    sub_code=sub_code,
                    amount=amount,
                    comment=comment
                )
                try:
                    response = await api_client.add_expense(expense)
                    task_id = response.task_id
                    if not task_id:
                        raise ValueError("No task_id in response")
                    task_ids.append(task_id)
                except Exception as e:
                    logger.error(f"API error adding dividends expense: {e}")
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при добавлении расхода (Дивиденды):\n{operation_info}\n\n{e} ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                    return await bot.send_message(
                        chat_id=chat_id,
                        text="Выберите следующую операцию: 🔄",
                        reply_markup=create_start_kb()
                    )

                if await check_task_status(api_client, task_id):
                    animation_task.cancel()
                    await delete_tracked_messages(bot, state, chat_id)
                    await state.update_data(messages_to_delete=[])
                    await send_success_message(
                        bot, chat_id, message_id,
                        f"{html.bold('Расход (Дивиденды) успешно добавлен')} ✅\n{operation_info}",
                        task_ids, state, operation_info
                    )
                else:
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка при добавлении расхода (Дивиденды):\n{operation_info}\n\nТайм-аут сервера ❌",
                        reply_markup=None,
                        parse_mode="HTML"
                    )

        except Exception as e:
            logger.error(f"Error processing expense operation: {e}")
            animation_task.cancel()
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"Произошла ошибка:\n{operation_info}\n\n{e} ❌",
                reply_markup=None,
                parse_mode="HTML"
            )

        # Очищаем состояние, сохраняя operation_message_text и task_ids
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

    @confirm_router.callback_query(Expense.confirm, ConfirmOperationCallback.filter(F.confirm == False))
    @track_messages
    async def cancel_operation(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id

        logger.info(f"Пользователь {user_id} отменил операцию, message_id={message_id}")

        # Форматируем сообщение с полной информацией
        data = await state.get_data()
        operation_info = await format_operation_message(data, api_client)

        # Удаляем все сообщения
        await delete_tracked_messages(bot, state, chat_id)
        await delete_key_messages(bot, state, chat_id)
        await state.update_data(messages_to_delete=[])

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"Добавление расхода отменено:\n{operation_info} 🚫",
                reply_markup=None,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id}: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"Добавление расхода отменено:\n{operation_info} 🚫",
                reply_markup=None,
                parse_mode="HTML"
            )

        await state.clear()
        start_message = await bot.send_message(
            chat_id=chat_id,
            text="Выберите следующую операцию: 🔄",
            reply_markup=create_start_kb()
        )
        return start_message

    return confirm_router
