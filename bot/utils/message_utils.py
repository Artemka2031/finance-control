from functools import wraps
from typing import Union, Optional, List

from aiogram import Bot
from aiogram import html
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
import asyncio

from .logging import configure_logger
from ..api_client import ApiClient
from ..keyboards.delete import create_delete_operation_kb

# Configure utils logger
logger = configure_logger("[UTILS]", "blue")

# Список ключевых полей для сообщений по состояниям
KEY_MESSAGE_FIELDS = {
    "Expense:date": "date_message_id",
    "Expense:wallet": "wallet_message_id",
    "Expense:chapter_code": "status_message_id",
    "Expense:category_code": "status_message_id",
    "Expense:subcategory_code": "status_message_id",
    "Expense:amount": "amount_message_id",
    "Expense:coefficient": "coefficient_message_id",
    "Expense:comment": "comment_message_id",
    "Expense:creditor_borrow": "creditor_message_id",
    "Expense:creditor_return": "creditor_message_id",
    "Income:date": "date_message_id",
    "Income:category_code": "category_message_id",
    "Income:amount": "amount_message_id",
    "Income:comment": "comment_message_id",
    "Income:confirm": "comment_message_id",
    "Income:delete_income": "comment_message_id",
    "AI:clarify:chapter_code": "clarification_message_id",
    "AI:clarify:category_code": "clarification_message_id",
    "AI:clarify:subcategory_code": "clarification_message_id",
    "AI:clarify:creditor": "clarification_message_id",
    "AI:clarify:amount": "clarification_message_id",
    "AI:clarify:date": "clarification_message_id",
    "AI:clarify:coefficient": "clarification_message_id",
    "AI:clarify:comment": "clarification_message_id",
    "AI:confirm": "confirmation_message_id",
}


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


async def send_success_message(bot: Bot, chat_id: int, message_id: int, text: str, task_ids: List[str],
                               state: FSMContext, operation_info: str) -> None:
    logger.info(f"Sending success message for tasks {task_ids} to chat {chat_id}")
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


def track_messages(func):
    @wraps(func)
    async def wrapper(event: Union[Message, CallbackQuery], state: FSMContext, bot: Bot, *args, **kwargs):
        if isinstance(event, Message):
            chat_id = event.chat.id
            user_id = event.from_user.id
            event_type = "Message"
            event_id = event.message_id
        elif isinstance(event, CallbackQuery):
            if not event.message:
                logger.warning(f"Нет сообщения в CallbackQuery от пользователя {event.from_user.id}")
                return await func(event, state, bot, *args, **kwargs)
            chat_id = event.message.chat.id
            user_id = event.from_user.id
            event_type = "CallbackQuery"
            event_id = event.message.message_id
        else:
            logger.error(f"Неподдерживаемый тип события: {type(event).__name__}")
            return await func(event, state, bot, *args, **kwargs)

        current_state = await state.get_state() or "AI:default"
        if "AI" in func.__module__ and not current_state.startswith("AI:"):
            current_state = f"AI:clarify:{(await state.get_data()).get('agent_state', {}).get('actions', [{}])[0].get('clarification_field', 'default')}"
            if any(out.get("state") == "Expense:confirm" for out in
                   (await state.get_data()).get("agent_state", {}).get("output", [])):
                current_state = "AI:confirm"

        logger.debug(
            f"Обработка {event_type} (id={event_id}) в чате {chat_id} от пользователя {user_id}, состояние={current_state}")

        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", []).copy()

        try:
            result = await func(event, state, bot, *args, **kwargs)
        except Exception as e:
            logger.error(f"Ошибка в обработчике {func.__name__}: {e}")
            raise

        key_field = KEY_MESSAGE_FIELDS.get(current_state)
        if isinstance(result, Message):
            if key_field:
                old_key_message_id = data.get(key_field)
                if old_key_message_id and old_key_message_id != result.message_id and old_key_message_id not in messages_to_delete:
                    messages_to_delete.append(old_key_message_id)
                    logger.debug(
                        f"Старое ключевое сообщение {old_key_message_id} ({key_field}) добавлено в messages_to_delete")
                await state.update_data({key_field: result.message_id, "messages_to_delete": messages_to_delete})
                logger.debug(f"Сохранено ключевое сообщение {result.message_id} в {key_field}")
            else:
                if result.message_id != event_id and result.message_id not in messages_to_delete:
                    messages_to_delete.append(result.message_id)
                    logger.debug(f"Добавлено временное сообщение {result.message_id} в messages_to_delete")
                    await state.update_data(messages_to_delete=messages_to_delete)
        elif result is None:
            logger.warning(f"Обработчик {func.__name__} вернул None")

        if isinstance(event, CallbackQuery) and key_field:
            data = await state.get_data()
            current_key_message_id = data.get(key_field)
            if current_key_message_id == event.message.message_id and event.message.message_id not in messages_to_delete:
                logger.debug(f"Отредактированное сообщение {event.message.message_id} является ключевым ({key_field})")
            elif event.message.message_id not in messages_to_delete and event.message.message_id != (
                    result.message_id if isinstance(result, Message) else None):
                messages_to_delete.append(event.message.message_id)
                logger.debug(f"Добавлено отредактированное сообщение {event.message.message_id} в messages_to_delete")
                await state.update_data(messages_to_delete=messages_to_delete)

        return result

    return wrapper


async def delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.debug(f"Удалено сообщение {message_id} в чате {chat_id}")
        return True
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")
        return False


async def delete_tracked_messages(bot: Bot, state: FSMContext, chat_id: int,
                                  exclude_message_id: Optional[int] = None) -> None:
    data = await state.get_data()
    messages_to_delete = data.get("messages_to_delete", []).copy()
    key_message_ids = [data.get(field) for field in set(KEY_MESSAGE_FIELDS.values()) if data.get(field)]

    if not messages_to_delete:
        logger.debug(f"Нет временных сообщений для удаления в чате {chat_id}")
        return

    logger.debug(f"Удаление временных сообщений {messages_to_delete} в чате {chat_id}, исключая {exclude_message_id}")
    updated_messages = messages_to_delete.copy()

    for msg_id in messages_to_delete:
        if msg_id and msg_id not in key_message_ids and msg_id != exclude_message_id:
            if await delete_message(bot, chat_id, msg_id) or True:
                updated_messages.remove(msg_id)
        else:
            updated_messages.remove(msg_id)

    await state.update_data(messages_to_delete=updated_messages)
    logger.info(f"Очищен список messages_to_delete в чате {chat_id}, новый список: {updated_messages}")


async def delete_key_messages(bot: Bot, state: FSMContext, chat_id: int,
                              exclude_message_id: Optional[int] = None) -> None:
    data = await state.get_data()
    key_message_ids = [data.get(field) for field in set(KEY_MESSAGE_FIELDS.values()) if data.get(field)]

    if not key_message_ids:
        logger.debug(f"Нет ключевых сообщений для удаления в чате {chat_id}")
        return

    logger.debug(f"Удаление ключевых сообщений {key_message_ids} в чате {chat_id}, исключая {exclude_message_id}")
    for msg_id in key_message_ids:
        if msg_id != exclude_message_id:
            await delete_message(bot, chat_id, msg_id)

    update_data = {
        field: None if data.get(field) != exclude_message_id else data.get(field)
        for field in set(KEY_MESSAGE_FIELDS.values())
    }
    update_data["messages_to_delete"] = data.get("messages_to_delete", [])
    await state.update_data(**update_data)
    logger.info(f"Очищены ключевые сообщения в чате {chat_id}, исключая {exclude_message_id}")


async def format_operation_message(data: dict, api_client: ApiClient, include_amount: bool = True) -> str:
    date = data.get("date", "")
    wallet = data.get("wallet", "")
    wallet_name = {"project": "Проект", "borrow": "Взять в долг", "repay": "Вернуть долг"}.get(wallet, wallet)
    sec_code = data.get("chapter_code", "")
    cat_code = data.get("category_code", "")
    sub_code = data.get("subcategory_code", "")
    amount = data.get("amount", 0) if include_amount else None
    comment = data.get("comment", "")
    creditor = data.get("creditor", "")
    creditor_name = data.get("creditor_name", creditor)
    coefficient = data.get("coefficient", 1.0)

    section_name = category_name = subcategory_name = ""
    try:
        if sec_code:
            sections = await api_client.get_sections()
            section_name = next((sec.name for sec in sections if sec.code == sec_code), "")
        if cat_code:
            categories = await api_client.get_categories(sec_code)
            category_name = next((cat.name for cat in categories if cat.code == cat_code), "")
        if sub_code:
            subcategories = await api_client.get_subcategories(sec_code, cat_code)
            subcategory_name = next((sub.name for sub in subcategories if sub.code == sub_code), "")
        if creditor:
            creditors = await api_client.get_creditors()
            creditor_name = next((cred.name for cred in creditors if cred.code == creditor), creditor)
        logger.debug(
            f"Retrieved names: section={section_name}, category={category_name}, subcategory={subcategory_name}, creditor={creditor_name}")
    except Exception as e:
        logger.warning(f"Error retrieving category names: {e}")

    message_lines = []
    if date:
        message_lines.append(f"Дата: 🗓️ {html.code(date)}")
    if wallet_name:
        message_lines.append(f"Кошелёк: 💸 {html.code(wallet_name)}")
    if section_name:
        message_lines.append(f"Раздел: 📕 {html.code(section_name)}")
    if category_name:
        message_lines.append(f"Категория: 🏷️ {html.code(category_name)}")
    if subcategory_name:
        message_lines.append(f"Подкатегория: 🏷️ {html.code(subcategory_name)}")
    if creditor_name and wallet in ["borrow", "repay"]:
        message_lines.append(f"Кредитор: 👤 {html.code(creditor_name)}")
    if coefficient != 1.0 and wallet == "borrow":
        message_lines.append(f"Коэффициент: 📊 {html.code(coefficient)}")
    if amount is not None:
        message_lines.append(f"Сумма: 💰 {html.code(amount)} ₽")
    if comment:
        message_lines.append(f"Комментарий: 💬 {html.code(comment)}")

    return "\n".join(message_lines)
