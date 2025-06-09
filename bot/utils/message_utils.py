# bot/utils/message_utils.py
from __future__ import annotations

import asyncio
from functools import wraps
from typing import Union, Optional, List

from aiogram import Bot, html
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from api_client import ApiClient
from keyboards.delete import create_delete_operation_kb
from utils.logging import configure_logger

# ------------------------------------------------------------------ #
# 1. Логгер                                                          #
# ------------------------------------------------------------------ #
logger = configure_logger("[UTILS]", "blue")

# ------------------------------------------------------------------ #
# 2. Константы                                                       #
# ------------------------------------------------------------------ #
KEY_MESSAGE_FIELDS = {
    #  Expense
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
    #  Income
    "Income:date": "date_message_id",
    "Income:category_code": "category_message_id",
    "Income:amount": "amount_message_id",
    "Income:comment": "comment_message_id",
    "Income:confirm": "comment_message_id",
    "Income:delete_income": "comment_message_id",
    #  AI – clarify / confirm
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

# ------------------------------------------------------------------ #
# 3. Анимация «…»                                                    #
# ------------------------------------------------------------------ #
async def animate_processing(bot: Bot, chat_id: int, message_id: int, base_text: str) -> None:
    dots = [".", "..", "..."]
    while True:
        for d in dots:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{base_text}\n\n⏳ Обрабатываем операцию{d} ",
                    parse_mode="HTML",
                )
                await asyncio.sleep(0.5)
            except Exception:
                return  # любое исключение = остановить анимацию


# ------------------------------------------------------------------ #
# 4. Успешное завершение                                             #
# ------------------------------------------------------------------ #
async def send_success_message(
        bot: Bot,
        chat_id: int,
        message_id: int,
        text: str,
        task_ids: List[str],
        state: FSMContext,
        operation_info: str,
) -> None:
    valid_task_ids = [tid for tid in task_ids if tid]
    data = await state.get_data()
    messages_to_delete = data.get("messages_to_delete", []).copy()

    # Удаляем message_id из списка временных сообщений
    if message_id in messages_to_delete:
        messages_to_delete.remove(message_id)
        logger.debug(f"Удалено подтверждённое сообщение {message_id} из messages_to_delete")

    await state.update_data(
        operation_message_text=operation_info,
        task_ids=valid_task_ids,
        messages_to_delete=messages_to_delete,
    )
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=create_delete_operation_kb(valid_task_ids, confirm=False),
            parse_mode="HTML",
        )
    except Exception:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=create_delete_operation_kb(valid_task_ids, confirm=False),
            parse_mode="HTML",
        )


# ------------------------------------------------------------------ #
# 5. Форматирование операций                                         #
# ------------------------------------------------------------------ #
async def format_operation_message(
        data: dict,
        api_client: ApiClient,
        include_amount: bool = True,
) -> str:
    """Составляет красивый текст операции (расход/долг)."""
    date = data.get("date", "")
    wallet_code = data.get("wallet", "")
    wallet_name = {
        "project": "Проект",
        "borrow": "Взять в долг",
        "repay": "Вернуть долг",
    }.get(wallet_code, wallet_code)

    sec_code = data.get("chapter_code", "")
    cat_code = data.get("category_code", "")
    sub_code = data.get("subcategory_code", "")
    amount = data.get("amount") if include_amount else None
    comment = data.get("comment", "")

    creditor = data.get("creditor", "")
    creditor_name = data.get("creditor_name", creditor)
    coefficient = data.get("coefficient", 1.0)

    # Читаем названия из БД/АПИ
    section_name = category_name = subcategory_name = ""
    try:
        if sec_code:
            section_name = next(
                (s.name for s in await api_client.get_sections() if s.code == sec_code),
                "",
            )
        if cat_code:
            category_name = next(
                (
                    c.name
                    for c in await api_client.get_categories(sec_code)
                    if c.code == cat_code
                ),
                "",
            )
        if sub_code:
            subcategory_name = next(
                (
                    s.name
                    for s in await api_client.get_subcategories(sec_code, cat_code)
                    if s.code == sub_code
                ),
                "",
            )
        if creditor:
            creditor_name = next(
                (c.name for c in await api_client.get_creditors() if c.code == creditor),
                creditor,
            )
    except Exception as e:
        logger.warning(f"Не смог получить метаданные: {e}")

    lines: list[str] = []
    if date:
        lines.append(f"Дата: 🗓️ {html.code(date)}")
    if wallet_name:
        lines.append(f"Кошелёк: 💸 {html.code(wallet_name)}")
    if section_name:
        lines.append(f"Раздел: 📕 {html.code(section_name)}")
    if category_name:
        lines.append(f"Категория: 🏷️ {html.code(category_name)}")
    if subcategory_name:
        lines.append(f"Подкатегория: 🏷️ {html.code(subcategory_name)}")
    if creditor_name and wallet_code in ("borrow", "repay", "Взять в долг", "Вернуть долг"):
        lines.append(f"Кредитор: 👤 {html.code(creditor_name)}")
    if coefficient != 1.0 and wallet_code in ("borrow", "Взять в долг"):
        lines.append(f"Коэффициент: 📊 {html.code(coefficient)}")
    if amount is not None:
        lines.append(f"Сумма: 💰 {html.code(amount)} ₽")
    if comment:
        lines.append(f"Комментарий: 💬 {html.code(comment)}")

    return "\n".join(lines)


async def format_income_message(data: dict, api_client: ApiClient) -> str:
    """Красивый текст для дохода."""
    date = data.get("date", "")
    category_code = data.get("category_code", "")
    amount = data.get("amount", 0)
    comment = data.get("comment", "")

    category_name = ""
    try:
        if category_code:
            categories = await api_client.get_incomes()
            category_name = next((cat.name for cat in categories if cat.code == category_code), category_code)
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


# ------------------------------------------------------------------ #
# 6. Удаление сообщений                                              #
# ------------------------------------------------------------------ #
async def delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    """
    Пытается удалить сообщение.
    True  – сообщение удалено **или уже отсутствовало**;
    False – удалить не удалось (любая иная ошибка).
    """
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.debug(f"Удалено сообщение {message_id} в чате {chat_id}")
        return True
    except TelegramBadRequest as e:
        # Сообщение уже удалено кем-то или ботом раньше – считаем успехом
        if "message to delete not found" in str(e):
            logger.debug(f"Сообщение {message_id} в чате {chat_id} уже отсутствует")
            return True
        logger.warning(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")
        return False


async def delete_tracked_messages(
        bot: Bot,
        state: FSMContext,
        chat_id: int,
        exclude_message_id: Optional[int] = None,
        exclude_confirmed: bool = True,
) -> None:
    """
    Удаляет все временные (non-key) сообщения и
    очищает список `messages_to_delete` в state.
    """
    data = await state.get_data()
    messages_to_delete = data.get("messages_to_delete", []).copy()
    key_message_ids = [data.get(field) for field in set(KEY_MESSAGE_FIELDS.values()) if data.get(field)]
    confirmed_message_ids = [
        data.get("confirmation_message_id")
        for task_id in data.get("task_ids", [])
        if data.get("confirmation_message_id")
    ]

    if not messages_to_delete:
        logger.debug(f"Нет временных сообщений для удаления в чате {chat_id}")
        return

    logger.debug(f"Удаление временных сообщений {messages_to_delete} в чате {chat_id}, исключая {exclude_message_id}")
    updated_messages = messages_to_delete.copy()

    for msg_id in messages_to_delete:
        # Пропускаем подтверждённые / ключевые / исключённое
        if (
                msg_id
                and (not exclude_confirmed or msg_id not in confirmed_message_ids)
                and msg_id not in key_message_ids
                and msg_id != exclude_message_id
        ):
            if await delete_message(bot, chat_id, msg_id):
                # «True» – удалено или не найдено → выводим из списка
                updated_messages.remove(msg_id)
        else:
            updated_messages.remove(msg_id)

    await state.update_data(messages_to_delete=updated_messages)
    logger.info(f"Очищен список messages_to_delete в чате {chat_id}, новый список: {updated_messages}")


async def delete_key_messages(
        bot: Bot,
        state: FSMContext,
        chat_id: int,
        exclude_message_id: Optional[int] = None,
) -> None:
    """
    Удаляет ключевые сообщения (даты, суммы, подтверждения).
    """
    data = await state.get_data()
    key_message_ids = [data.get(field) for field in set(KEY_MESSAGE_FIELDS.values()) if data.get(field)]

    if not key_message_ids:
        logger.debug(f"Нет ключевых сообщений для удаления в чате {chat_id}")
        return

    logger.debug(f"Удаление ключевых сообщений {key_message_ids} в чате {chat_id}, исключая {exclude_message_id}")
    update_data = {
        field: None if data.get(field) != exclude_message_id else data.get(field)
        for field in set(KEY_MESSAGE_FIELDS.values())
    }
    update_data["messages_to_delete"] = data.get("messages_to_delete", [])

    for msg_id in key_message_ids:
        if msg_id != exclude_message_id:
            if await delete_message(bot, chat_id, msg_id):
                for field in KEY_MESSAGE_FIELDS.values():
                    if data.get(field) == msg_id:
                        update_data[field] = None

    await state.update_data(**update_data)
    logger.info(f"Очищены ключевые сообщения в чате {chat_id}, исключая {exclude_message_id}")


# ------------------------------------------------------------------ #
# 7. Автоматическая отмена по таймеру                                #
# ------------------------------------------------------------------ #
async def cancel_expired_message(
        bot: Bot,
        chat_id: int,
        message_id: int,
        state: FSMContext,
        timeout: int = 30,
) -> None:
    """
    Через `timeout` секунд отменяет неподтверждённое сообщение.
    """
    try:
        await asyncio.sleep(timeout)
        data = await state.get_data()
        if data.get("last_interaction_time", 0) + timeout <= asyncio.get_event_loop().time():
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⌛ Время истекло",
                parse_mode="HTML",
                reply_markup=None,
            )
            agent_state = data.get("agent_state", {})
            if agent_state:
                agent_state["requests"] = []
                await state.update_data(agent_state=agent_state)
            logger.info(f"Сообщение {message_id} в чате {chat_id} автоматически отменено по таймеру")
    except Exception as e:
        logger.warning(f"Ошибка при автоматической отмене сообщения {message_id}: {e}")


# ------------------------------------------------------------------ #
# 8. Трекер сообщений                                                #
# ------------------------------------------------------------------ #
def track_messages(func):
    """
    Декоратор-трекер: фиксирует все отправленные/отредактированные сообщения
    и распределяет их по ключевым / временным спискам.
    """
    @wraps(func)
    async def wrapper(event: Union[Message, CallbackQuery], state: FSMContext, bot: Bot, *args, **kwargs):
        # --- идентификация события ---
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
            current_state = "AI:clarify:default"

        logger.debug(
            f"Обработка {event_type} (id={event_id}) в чате {chat_id} от пользователя {user_id}, состояние={current_state}"
        )

        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", []).copy()

        # --- выполняем сам обработчик ---
        try:
            result = await func(event, state, bot, *args, **kwargs)
        except Exception as e:
            logger.error(f"Ошибка в обработчике {func.__name__}: {e}")
            raise

        # --- пост-обработка отправленных сообщений ---
        key_field = KEY_MESSAGE_FIELDS.get(current_state)
        if isinstance(result, Message):
            if key_field:
                old_key_message_id = data.get(key_field)
                if old_key_message_id and old_key_message_id != result.message_id and old_key_message_id not in messages_to_delete:
                    messages_to_delete.append(old_key_message_id)
                await state.update_data({key_field: result.message_id, "messages_to_delete": messages_to_delete})
            else:
                if result.message_id != event_id and result.message_id not in messages_to_delete:
                    messages_to_delete.append(result.message_id)
                    await state.update_data(messages_to_delete=messages_to_delete)
        elif result is None:
            logger.warning(f"Обработчик {func.__name__} вернул None")

        if isinstance(event, CallbackQuery) and key_field:
            data = await state.get_data()
            current_key_message_id = data.get(key_field)
            if current_key_message_id == event.message.message_id:
                pass  # ключевое сообщение – уже учтено
            elif event.message.message_id not in messages_to_delete and (
                    not isinstance(result, Message) or event.message.message_id != result.message_id
            ):
                messages_to_delete.append(event.message.message_id)
                await state.update_data(messages_to_delete=messages_to_delete)

        # время последнего взаимодействия
        await state.update_data(last_interaction_time=asyncio.get_event_loop().time())

        return result

    return wrapper


# ------------------------------------------------------------------ #
# 9. Проверка статуса задачи                                         #
# ------------------------------------------------------------------ #
async def check_task_status(api_client: ApiClient, task_id: str, max_attempts: int = 10, delay: float = 2.0) -> bool:
    """Опрос фоновой задачи сервера."""
    for attempt in range(max_attempts):
        try:
            status = await api_client.get_task_status(task_id)
            if status.get("status") == "completed":
                logger.info(f"Task {task_id} completed successfully")
                return True
            elif status.get("status") in ("failed", "error"):
                logger.error(f"Task {task_id} failed: {status.get('error', 'Unknown error')}")
                return False
        except Exception as e:
            logger.warning(f"Error checking task {task_id} status: {e}")
        await asyncio.sleep(delay)
    logger.warning(f"Task {task_id} timed out after {max_attempts} attempts")
    return False
