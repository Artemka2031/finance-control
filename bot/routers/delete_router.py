import asyncio
import re

from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ..api_client import ApiClient
from ..keyboards.delete import create_delete_operation_kb
from ..keyboards.utils import DeleteOperationCallback, ConfirmDeleteOperationCallback
from ..utils.logging import configure_logger

logger = configure_logger("[DELETE]", "red")


async def check_task_status(api_client: ApiClient, task_id: str, max_attempts: int = 3, delay: float = 1.0) -> dict:
    """Проверяет статус задачи. Возвращает словарь с полным статусом задачи."""
    for attempt in range(max_attempts):
        try:
            status = await api_client.get_task_status(task_id)
            task_status = status.get("status")
            task_type = status.get("task_type", "unknown")
            if task_status == "completed":
                logger.info(f"Task {task_id} ({task_type}) is completed")
                return status
            elif task_status in ["failed", "error"]:
                logger.error(
                    f"Task {task_id} ({task_type}) failed: {status.get('result', {}).get('error', 'Unknown error')}")
                return status
            logger.debug(f"Task {task_id} ({task_type}) still pending, attempt {attempt + 1}/{max_attempts}")
            await asyncio.sleep(delay)
        except Exception as e:
            if "not found" in str(e).lower():
                logger.warning(f"Task {task_id} not found")
                return {"status": "not_found", "task_type": "unknown"}
            logger.warning(f"Error checking task {task_id} status: {e}")
            await asyncio.sleep(delay)
    logger.warning(f"Task {task_id} timed out after {max_attempts} attempts")
    return {"status": "pending", "task_type": "unknown"}


async def animate_deleting(bot: Bot, chat_id: int, message_id: int, base_text: str) -> None:
    """Запускает анимацию удаления в отдельной задаче."""
    dots = [".", "..", "..."]
    while True:
        for dot in dots:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{base_text}\n\nУдаляем операцию{dot} ⏳",
                    reply_markup=None,
                    parse_mode="HTML"
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Failed to animate deleting for message {message_id}: {e}")
                return


def create_delete_router(bot: Bot, api_client: ApiClient):
    delete_router = Router()

    @delete_router.callback_query(DeleteOperationCallback.filter())
    async def request_delete_operation(query: CallbackQuery, callback_data: DeleteOperationCallback, state: FSMContext,
                                       bot: Bot) -> None:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        task_ids = callback_data.task_ids.split(",") if callback_data.task_ids != "noop" else []

        logger.info(f"Пользователь {user_id} запросил удаление операций task_ids={task_ids}")

        if not task_ids:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="Ошибка: нет операций для удаления. ❌",
                reply_markup=create_delete_operation_kb([], confirm=False),
                parse_mode="HTML"
            )
            return

        # Получаем сохранённый текст операции из состояния
        data = await state.get_data()
        operation_info = data.get("operation_message_text", "Операция")
        # Удаляем служебный текст об успешной записи, если он есть
        operation_info = re.sub(r"^(?:.*✅.*?\n)?", "", operation_info, flags=re.MULTILINE)

        # Проверяем статус задач
        all_already_deleted = True
        valid_task_ids = []
        for task_id in task_ids:
            if not task_id:
                logger.warning(f"Invalid task_id: {task_id}")
                continue

            status = await check_task_status(api_client, task_id)
            if status.get("status") == "not_found":
                logger.info(f"Task {task_id} does not exist")
                continue
            else:
                valid_task_ids.append(task_id)
                all_already_deleted = False

        if all_already_deleted:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"Операция уже удалена или не существует. ✅\n{operation_info}",
                reply_markup=None,
                parse_mode="HTML"
            )
            await state.clear()
            return

        if not valid_task_ids:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="Ошибка: нет валидных операций для удаления. ❌",
                reply_markup=create_delete_operation_kb([], confirm=False),
                parse_mode="HTML"
            )
            return

        # Запрашиваем подтверждение удаления
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"Подтвердите удаление:\n{operation_info}",
            reply_markup=create_delete_operation_kb(valid_task_ids, confirm=True),
            parse_mode="HTML"
        )

    @delete_router.callback_query(ConfirmDeleteOperationCallback.filter())
    async def confirm_delete_operation(query: CallbackQuery, callback_data: ConfirmDeleteOperationCallback,
                                       state: FSMContext, bot: Bot) -> None:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        task_ids = callback_data.task_ids.split(",") if callback_data.task_ids != "noop" else []

        logger.info(f"Пользователь {user_id} подтвердил/отменил удаление операций task_ids={task_ids}")

        if not task_ids:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="Ошибка: нет операций для удаления. ❌",
                reply_markup=create_delete_operation_kb([], confirm=False),
                parse_mode="HTML"
            )
            return

        # Получаем сохранённый текст операции из состояния
        data = await state.get_data()
        operation_info = data.get("operation_message_text", "Операция")
        # Удаляем служебный текст об успешной записи, если он есть
        operation_info = re.sub(r"^(?:.*✅.*?\n)?", "", operation_info, flags=re.MULTILINE)

        if callback_data.confirm_delete:
            # Запускаем анимацию удаления
            animation_task = asyncio.create_task(animate_deleting(bot, chat_id, message_id, operation_info))

            success = True
            valid_task_ids = []
            error_messages = []

            # Маппинг task_type на метод удаления
            remove_methods = {
                "add_expense": api_client.remove_expense,
                "add_income": api_client.remove_income,
                "record_borrowing": api_client.remove_borrowing,
                "record_repayment": api_client.remove_repayment,
                "record_saving": api_client.remove_saving,
            }

            for task_id in task_ids:
                if not task_id:
                    logger.warning(f"Skipping invalid task_id: {task_id}")
                    error_messages.append(f"Некорректный task_id: {task_id}")
                    success = False
                    continue

                # Получаем статус и тип задачи
                status = await check_task_status(api_client, task_id)
                task_type = status.get("task_type", "unknown")
                task_status = status.get("status")

                if task_status == "not_found":
                    logger.info(f"Task {task_id} does not exist")
                    continue

                if task_type not in remove_methods:
                    error_msg = f"Некорректный тип операции для task_id={task_id}: {task_type}"
                    logger.warning(error_msg)
                    error_messages.append(error_msg)
                    success = False
                    valid_task_ids.append(task_id)
                    continue

                # Выбираем метод удаления
                remove_method = remove_methods[task_type]
                try:
                    response = await remove_method(task_id)
                    if response.ok and response.task_id:
                        remove_task_id = response.task_id
                        logger.info(f"Initiated {task_type} deletion with task_id={remove_task_id} for task {task_id}")
                        remove_status = await check_task_status(api_client, remove_task_id)
                        if remove_status.get("status") == "completed":
                            logger.info(
                                f"Успешно удалён {task_type} task_id={task_id} (remove_task_id={remove_task_id})")
                        else:
                            error_msg = f"Не удалось удалить {task_type} (task_id={task_id}): {remove_status.get('result', {}).get('error', 'неизвестная ошибка')}"
                            logger.warning(error_msg)
                            error_messages.append(error_msg)
                            success = False
                    else:
                        error_msg = f"Не удалось удалить {task_type} (task_id={task_id}): {response.detail or 'неизвестная ошибка'}"
                        logger.warning(error_msg)
                        error_messages.append(error_msg)
                        success = False
                except Exception as e:
                    error_msg = f"Ошибка при удалении {task_type} (task_id={task_id}): {e}"
                    logger.error(error_msg)
                    error_messages.append(error_msg)
                    success = False

                valid_task_ids.append(task_id)

            # Останавливаем анимацию
            animation_task.cancel()

            if success and valid_task_ids:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"Операция успешно удалена! ✅\n{operation_info}",
                    reply_markup=None,
                    parse_mode="HTML"
                )
                await state.clear()
            elif not valid_task_ids:
                error_text = "Ошибка: нет валидных операций для удаления. ❌"
                if error_messages:
                    error_text += "\n" + "\n".join(error_messages)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{error_text}\n{operation_info}",
                    reply_markup=None,
                    parse_mode="HTML"
                )
            else:
                error_text = "Ошибка при удалении операции: Попробуйте снова. ❌"
                if error_messages:
                    error_text += "\n" + "\n".join(error_messages)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{error_text}\n{operation_info}",
                    reply_markup=create_delete_operation_kb(valid_task_ids, confirm=False),
                    parse_mode="HTML"
                )
        else:
            # Отмена удаления
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"Удаление операции отменено 🚫\n{operation_info}",
                reply_markup=create_delete_operation_kb(task_ids, confirm=False),
                parse_mode="HTML"
            )

    return delete_router
