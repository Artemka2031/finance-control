import asyncio
from datetime import datetime
from typing import Optional

from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ..agent.agent import Agent
from ..agent.agents.serialization import deserialize_callback_data, serialize_messages, create_aiogram_keyboard
from ..agent.utils import agent_logger
from ..api_client import ApiClient, CreditorIn, ExpenseIn
from ..keyboards.delete import create_delete_operation_kb
from ..keyboards.start_kb import create_start_kb
from ..utils.message_utils import track_messages, delete_tracked_messages, format_operation_message


async def check_task_status(api_client: ApiClient, task_id: str, max_attempts: int = 10, delay: float = 2.0) -> bool:
    for attempt in range(max_attempts):
        try:
            status = await api_client.get_task_status(task_id)
            if status.get("status") == "completed":
                agent_logger.info(f"Task {task_id} completed successfully")
                return True
            elif status.get("status") in ["failed", "error"]:
                agent_logger.error(f"Task {task_id} failed: {status.get('error', 'Unknown error')}")
                return False
        except Exception as e:
            agent_logger.warning(f"Error checking task {task_id} status: {e}")
        agent_logger.debug(f"Task {task_id} still pending, attempt {attempt + 1}/{max_attempts}")
        await asyncio.sleep(delay)
    agent_logger.warning(f"Task {task_id} timed out after {max_attempts} attempts")
    return False


async def animate_processing(bot: Bot, chat_id: int, message_id: int, base_text: str) -> None:
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
                agent_logger.warning(f"Failed to animate processing for message {message_id}: {e}")
                return


async def send_success_message(bot: Bot, chat_id: int, message_id: int, text: str, task_ids: list[str],
                               state: FSMContext, operation_info: str) -> None:
    agent_logger.info(f"Sending success message for tasks {task_ids} to chat {chat_id}")
    valid_task_ids = [tid for tid in task_ids if tid is not None]
    if not valid_task_ids:
        agent_logger.error(f"No valid task_ids provided: {task_ids}")
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
        agent_logger.warning(f"Failed to edit success message {message_id}: {e}")
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=create_delete_operation_kb(valid_task_ids, confirm=False),
            parse_mode="HTML"
        )
        agent_logger.debug(f"Sent new success message {sent_message.message_id}")


def create_ai_router(bot: Bot, api_client: ApiClient):
    ai_router = Router()
    agent = Agent()

    @ai_router.message(F.text.contains("#ИИ"))
    @track_messages
    async def handle_ai_message(message: Message, state: FSMContext, bot: Bot) -> Message:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.replace("#ИИ", "").strip()
        if not input_text:
            agent_logger.warning(f"[AI_ROUTER] Пользователь {user_id} отправил пустое сообщение с #ИИ")
            return await bot.send_message(
                chat_id=chat_id,
                text="Пожалуйста, укажите запрос после #ИИ, например: #ИИ Купил кофе за 250",
                parse_mode="HTML"
            )

        agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} отправил запрос с #ИИ: {input_text}")
        await delete_tracked_messages(bot, state, chat_id)
        result = await agent.process_request(input_text, interactive=True)
        return await handle_agent_result(result, bot, state, chat_id, input_text)

    @ai_router.message()
    @track_messages
    async def handle_clarification_message(message: Message, state: FSMContext, bot: Bot) -> Optional[Message]:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.strip()
        data = await state.get_data()
        agent_state = data.get("agent_state")
        input_text_orig = data.get("input_text", "")

        if not agent_state or not agent_state.get("actions"):
            agent_logger.debug(f"[AI_ROUTER] Нет активного состояния для обработки сообщения от {user_id}")
            return None

        clarification_needed = False
        clarification_field = None
        request_index = None
        for action in agent_state["actions"]:
            if action["needs_clarification"]:
                clarification_field = action["clarification_field"]
                request_index = action["request_index"]
                clarification_needed = True
                break

        if not clarification_needed or not clarification_field:
            agent_logger.debug(f"[AI_ROUTER] Нет полей для уточнения для пользователя {user_id}")
            return None

        if clarification_field not in ["amount", "date", "coefficient", "comment"]:
            agent_logger.debug(f"[AI_ROUTER] Ожидается выбор через клавиатуру для поля {clarification_field}")
            return await bot.send_message(
                chat_id=chat_id,
                text=f"Пожалуйста, выберите {clarification_field} через клавиатуру.",
                parse_mode="HTML"
            )

        agent_logger.info(
            f"[AI_ROUTER] Пользователь {user_id} отправил уточнение для {clarification_field}: {input_text}")
        agent_state["requests"][request_index]["entities"][clarification_field] = input_text
        if clarification_field in agent_state["requests"][request_index]["missing"]:
            agent_state["requests"][request_index]["missing"].remove(clarification_field)
        agent_state["messages"].append({"role": "user", "content": f"Clarified: {clarification_field}={input_text}"})

        result = await agent.process_request(input_text_orig, interactive=True, prev_state=agent_state)
        return await handle_agent_result(result, bot, state, chat_id, input_text_orig,
                                         message_id=data.get("clarification_message_id"))

    @ai_router.callback_query(F.data.startswith("CS:") | F.data.startswith("cancel:"))
    @track_messages
    async def handle_category_selection(query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not query.message:
            agent_logger.warning(f"[AI_ROUTER] Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        selection = query.data

        agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} выбрал: {selection}")
        data = await state.get_data()
        prev_state = data.get("agent_state")
        input_text = data.get("input_text", "")

        if not prev_state and not selection.startswith("cancel:"):
            agent_logger.error(f"[AI_ROUTER] Нет предыдущего состояния для пользователя {user_id}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="Произошла ошибка: состояние утеряно. Пожалуйста, начните заново с #ИИ.",
                parse_mode="HTML"
            )
            return

        if selection.startswith("cancel:"):
            request_index = int(selection.split(":")[1])
            agent_logger.info(
                f"[AI_ROUTER] Пользователь {user_id} отменил уточнение для request_index: {request_index}")
            prev_state = deserialize_callback_data(selection, prev_state)
            await delete_tracked_messages(bot, state, chat_id, exclude_message_id=message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="Уточнение отменено.",
                parse_mode="HTML"
            )
            if not prev_state.get("requests"):
                await state.clear()
                await bot.send_message(
                    chat_id=chat_id,
                    text="Выберите следующую операцию: 🔄",
                    reply_markup=create_start_kb()
                )
            else:
                result = await agent.process_request(input_text, interactive=True, selection=selection,
                                                     prev_state=prev_state)
                await handle_agent_result(result, bot, state, chat_id, input_text, message_id)
            return

        prev_state = deserialize_callback_data(selection, prev_state)
        result = await agent.process_request(input_text, interactive=True, selection=selection, prev_state=prev_state)
        await handle_agent_result(result, bot, state, chat_id, input_text, message_id)

    @ai_router.callback_query(F.data.startswith("confirm_op:"))
    @track_messages
    async def handle_confirmation(query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not query.message:
            agent_logger.warning(f"[AI_ROUTER] Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        request_index = int(query.data.split(":")[1])

        data = await state.get_data()
        operation_info = data.get("operation_info", "Операция подтверждена")
        prev_state = data.get("agent_state", {})
        request = next((req for req in prev_state.get("requests", []) if req.get("index", 0) == request_index), None)

        if not request:
            agent_logger.error(f"[AI_ROUTER] Запрос для request_index {request_index} не найден")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="Произошла ошибка: запрос не найден.",
                parse_mode="HTML"
            )
            return

        if "confirm" in query.data:
            agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} подтвердил операцию")
            entities = request["entities"]
            operation_info = await format_operation_message(entities, api_client)
            animation_task = asyncio.create_task(animate_processing(bot, chat_id, message_id, operation_info))
            task_ids = []

            try:
                date = entities["date"]
                try:
                    date_obj = datetime.strptime(date, '%d.%m.%y' if len(date) == 8 else '%d.%m.%Y')
                    date = date_obj.strftime('%d.%m.%Y')
                except ValueError:
                    agent_logger.error(f"[AI_ROUTER] Invalid date format: {date}")
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Ошибка: Неверный формат даты\n{operation_info}\n\n❌",
                        parse_mode="HTML"
                    )
                    return

                wallet = entities["wallet"]
                if wallet == "project":
                    expense = ExpenseIn(
                        date=date,
                        sec_code=entities["chapter_code"],
                        cat_code=entities["category_code"],
                        sub_code=entities["subcategory_code"],
                        amount=float(entities["amount"]),
                        comment=entities["comment"]
                    )
                    response = await api_client.add_expense(expense)
                    if not response.ok or not response.task_id:
                        raise ValueError(f"Failed to add expense: {response.detail or 'No task_id'}")
                    task_id = response.task_id
                    task_ids.append(task_id)

                    if await check_task_status(api_client, task_id):
                        animation_task.cancel()
                        await send_success_message(
                            bot, chat_id, message_id,
                            f"{operation_info}\n\n✅ Расход успешно добавлен",
                            task_ids, state, operation_info
                        )
                    else:
                        raise ValueError("Task timed out")

                elif wallet == "borrow":
                    expense = ExpenseIn(
                        date=date,
                        sec_code=entities["chapter_code"],
                        cat_code=entities["category_code"],
                        sub_code=entities["subcategory_code"],
                        amount=float(entities["amount"]),
                        comment=entities["comment"]
                    )
                    borrowing = CreditorIn(
                        date=date,
                        cred_code=entities["creditor"],
                        amount=float(entities["amount"]),
                        comment=entities["comment"]
                    )
                    coefficient = float(entities["coefficient"])
                    saving_amount = round(float(entities["amount"]) * (1 - coefficient)) if coefficient != 1.0 else 0

                    response_expense = await api_client.add_expense(expense)
                    if not response_expense.ok or not response_expense.task_id:
                        raise ValueError(f"Failed to add expense: {response_expense.detail or 'No task_id'}")
                    response_borrowing = await api_client.record_borrowing(borrowing)
                    if not response_borrowing.ok or not response_borrowing.task_id:
                        raise ValueError(f"Failed to record borrowing: {response_borrowing.detail or 'No task_id'}")
                    task_ids.extend([response_expense.task_id, response_borrowing.task_id])

                    if saving_amount > 0:
                        saving = CreditorIn(
                            date=date,
                            cred_code=entities["creditor"],
                            amount=saving_amount,
                            comment=entities["comment"]
                        )
                        response_saving = await api_client.record_saving(saving)
                        if response_saving.ok and response_saving.task_id:
                            task_ids.append(response_saving.task_id)
                        else:
                            agent_logger.warning(f"Failed to record saving: {response_saving.detail or 'No task_id'}")

                    task_results = await asyncio.gather(
                        *(check_task_status(api_client, task_id) for task_id in task_ids if task_id))
                    if all(task_results):
                        animation_task.cancel()
                        await send_success_message(
                            bot, chat_id, message_id,
                            f"{operation_info}\n\n✅ Записан долг и расход",
                            task_ids, state, operation_info
                        )
                    else:
                        raise ValueError("Task timed out or failed")

                elif wallet == "repay":
                    repayment = CreditorIn(
                        date=date,
                        cred_code=entities["creditor"],
                        amount=float(entities["amount"]),
                        comment=entities["comment"]
                    )
                    response = await api_client.record_repayment(repayment)
                    if not response.ok or not response.task_id:
                        raise ValueError(f"Failed to record repayment: {response.detail or 'No task_id'}")
                    task_id = response.task_id
                    task_ids.append(task_id)

                    if await check_task_status(api_client, task_id):
                        animation_task.cancel()
                        await send_success_message(
                            bot, chat_id, message_id,
                            f"{operation_info}\n\n✅ Возврат долга",
                            task_ids, state, operation_info
                        )
                    else:
                        raise ValueError("Task timed out")

            except Exception as e:
                agent_logger.error(f"[AI_ROUTER] Error processing operation: {e}")
                animation_task.cancel()
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"Ошибка:\n{operation_info}\n\n{e} ❌",
                    parse_mode="HTML"
                )

        else:
            agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} отменил операцию")
            await delete_tracked_messages(bot, state, chat_id, exclude_message_id=message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{operation_info}\n\n🚫 Операция отменена",
                parse_mode="HTML"
            )

        if "confirm" not in query.data or task_ids:
            await state.clear()
            await bot.send_message(
                chat_id=chat_id,
                text="Выберите следующую операцию: 🔄",
                reply_markup=create_start_kb()
            )

    async def handle_agent_result(result: dict, bot: Bot, state: FSMContext, chat_id: int, input_text: str,
                                  message_id: Optional[int] = None) -> Message:
        agent_logger.info(f"[AI_ROUTER] Handling agent result for chat {chat_id}")
        messages = result.get("messages", [])
        output = result.get("output", [])

        serialized_messages = await serialize_messages(
            messages,
            api_client,
            result.get("state", {}).get("metadata", {}),
            output
        )
        agent_logger.debug(f"[AI_ROUTER] Serialized {len(serialized_messages)} messages")

        if not serialized_messages:
            agent_logger.error(f"[AI_ROUTER] Нет сообщений в результате обработки для чата {chat_id}")
            return await bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка при обработке запроса. Попробуйте снова.",
                parse_mode="HTML"
            )

        sent_message = None
        for message in serialized_messages:
            text = message.get("text", "")
            keyboard_data = message.get("keyboard")
            keyboard = await create_aiogram_keyboard(keyboard_data) if keyboard_data else None
            request_indices = message.get("request_indices", [])

            if not text:
                agent_logger.error(
                    f"[AI_ROUTER] Пустой текст сообщения для чата {chat_id}, request_indices: {request_indices}")
                text = "Произошла ошибка: пустое сообщение. Попробуйте снова."

            if result.get("state"):
                update_data = {
                    "agent_state": result["state"],
                    "input_text": input_text,
                    "operation_info": text,
                    "task_ids": [out["task_id"] for out in output if "task_id" in out]
                }
                if message.get("keyboard") and any(
                        btn.get("callback_data", "").startswith("API:fetch:") for row in
                        message.get("keyboard", {}).get("inline_keyboard", []) for btn in row
                ):
                    update_data["clarification_message_id"] = message_id or (
                        sent_message.message_id if sent_message else None)
                await state.update_data(**update_data)

            if message_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    agent_logger.info(f"[AI_ROUTER] Edited message {message_id} with text: {text[:50]}...")
                    sent_message = Message(message_id=message_id, chat=bot.get_chat(chat_id), text=text)
                except Exception as e:
                    agent_logger.warning(f"[AI_ROUTER] Не удалось отредактировать сообщение {message_id}: {e}")
                    sent_message = await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    agent_logger.info(
                        f"[AI_ROUTER] Sent new message {sent_message.message_id} with text: {text[:50]}...")
            else:
                sent_message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                agent_logger.info(f"[AI_ROUTER] Sent message {sent_message.message_id} with text: {text[:50]}...")
                if output:
                    await state.update_data(
                        message_id=sent_message.message_id,
                        operation_info=text,
                        task_ids=[out["task_id"] for out in output if "task_id" in out]
                    )

        return sent_message

    return ai_router
