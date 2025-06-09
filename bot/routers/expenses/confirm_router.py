# Bot/routers/expenses/confirm_router.py
import asyncio
from datetime import datetime

from aiogram import Router, Bot, html, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from api_client import ApiClient, ExpenseIn, CreditorIn
from keyboards.start_kb import create_start_kb
from keyboards.utils import ConfirmOperationCallback
from routers.expenses.state_classes import Expense
from utils.logging import configure_logger
from utils.message_utils import track_messages, format_operation_message, animate_processing, check_task_status, \
    delete_tracked_messages, send_success_message, delete_key_messages

logger = configure_logger("[CONFIRM]", "blue")


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
