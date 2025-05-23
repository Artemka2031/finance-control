# Bot/routers/ai_router/callback_handler.py
import asyncio
from datetime import datetime

from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .agent_processor import process_agent_request, handle_agent_result
from .states import MessageState
from ...agent.agent import Agent
from ...agent.agents.serialization import deserialize_callback_data
from ...api_client import ApiClient, CreditorIn, ExpenseIn, IncomeIn
from ...keyboards.start_kb import create_start_kb
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages, format_operation_message, check_task_status, \
    send_success_message, animate_processing

logger = configure_logger("[CALLBACK_HANDLER]", "magenta")


def create_callback_router(bot: Bot, api_client: ApiClient) -> Router:
    callback_router = Router()

    @callback_router.callback_query(F.data.startswith("CS:") | F.data.startswith("cancel:"))
    @track_messages
    async def handle_category_selection(query: CallbackQuery, state: FSMContext, bot: Bot,
                                        api_client: ApiClient) -> None:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        selection = query.data

        logger.info(f"Пользователь {user_id} выбрал: {selection}")
        data = await state.get_data()
        prev_state = data.get("agent_state")
        input_text = data.get("input_text", "")

        if not prev_state and not selection.startswith("cancel:"):
            logger.error(f"Нет предыдущего состояния для пользователя {user_id}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="😓 Ошибка: состояние утеряно. Начните заново с #ИИ",
                parse_mode="HTML"
            )
            return

        if selection.startswith("cancel:"):
            request_index = int(selection.split(":")[1])
            logger.info(f"Пользователь {user_id} отменил уточнение для request_index: {request_index}")
            prev_state = deserialize_callback_data(selection, prev_state)
            await delete_tracked_messages(bot, state, chat_id, exclude_message_id=message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ Уточнение отменено",
                parse_mode="HTML"
            )
            if not prev_state.get("requests"):
                await state.clear()
                await state.set_state(MessageState.waiting_for_ai_input)
                await bot.send_message(
                    chat_id=chat_id,
                    text="🔄 Выберите следующую операцию",
                    reply_markup=create_start_kb()
                )
            else:
                processing_message = await bot.send_message(
                    chat_id=chat_id,
                    text="🔍 Обрабатываем отмену...",
                    parse_mode="HTML"
                )
                agent = Agent(bot=bot, chat_id=chat_id, message_id=processing_message.message_id)
                result = await process_agent_request(agent, input_text, interactive=True, selection=selection,
                                                     prev_state=prev_state)
                await handle_agent_result(
                    result, bot, state, chat_id, input_text, api_client, message_id=processing_message.message_id
                )
            return

        prev_state = deserialize_callback_data(selection, prev_state)
        processing_message = await bot.send_message(
            chat_id=chat_id,
            text="🔍 Обрабатываем выбор...",
            parse_mode="HTML"
        )
        agent = Agent(bot=bot, chat_id=chat_id, message_id=processing_message.message_id)
        result = await process_agent_request(agent, input_text, interactive=True, selection=selection,
                                             prev_state=prev_state)
        await handle_agent_result(
            result, bot, state, chat_id, input_text, api_client, message_id=processing_message.message_id
        )

        return {"status": "processed"}

    @callback_router.callback_query(F.data.startswith("confirm_op:"))
    @track_messages
    async def handle_confirmation(query: CallbackQuery, state: FSMContext, bot: Bot, api_client: ApiClient) -> None:
        if not query.message:
            logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
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
            logger.error(f"Запрос для request_index {request_index} не найден")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="😓 Ошибка: запрос не найден",
                parse_mode="HTML"
            )
            return

        await state.set_state(MessageState.confirming_operation)
        entities = request["entities"]
        intent = request["intent"]

        if "confirm" in query.data:
            logger.info(f"Пользователь {user_id} подтвердил операцию")
            operation_info = await format_operation_message(entities, api_client)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⏳ Подтверждаем операцию...",
                parse_mode="HTML"
            )
            animation_task = asyncio.create_task(animate_processing(bot, chat_id, message_id, operation_info))
            task_ids = []

            try:
                date = entities["date"]
                try:
                    date_obj = datetime.strptime(date, '%d.%m.%y' if len(date) == 8 else '%d.%m.%Y')
                    date = date_obj.strftime('%d.%m.%Y')
                except ValueError:
                    logger.error(f"Неверный формат даты: {date}")
                    animation_task.cancel()
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"😓 Ошибка: неверный формат даты\n{operation_info}\n❌",
                        parse_mode="HTML"
                    )
                    return

                if intent == "add_income":
                    income = IncomeIn(
                        date=date,
                        cat_code=entities["category_code"],
                        amount=float(entities["amount"]),
                        comment=entities["comment"]
                    )
                    response = await api_client.add_income(income)
                    if not response.ok or not response.task_id:
                        raise ValueError(f"Не удалось добавить доход: {response.detail or 'No task_id'}")
                    task_ids.append(response.task_id)

                elif intent == "add_expense":
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
                        raise ValueError(f"Не удалось добавить расход: {response.detail or 'No task_id'}")
                    task_ids.append(response.task_id)

                elif intent == "borrow":
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
                    response_borrowing = await api_client.record_borrowing(borrowing)
                    if not response_expense.ok or not response_expense.task_id:
                        raise ValueError(f"Не удалось добавить расход: {response_expense.detail or 'No task_id'}")
                    if not response_borrowing.ok or not response_borrowing.task_id:
                        raise ValueError(f"Не удалось записать долг: {response_borrowing.detail or 'No task_id'}")
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
                            logger.warning(f"Не удалось записать сбережение: {response_saving.detail or 'No task_id'}")

                elif intent == "repay":
                    repayment = CreditorIn(
                        date=date,
                        cred_code=entities["creditor"],
                        amount=float(entities["amount"]),
                        comment=entities["comment"]
                    )
                    response = await api_client.record_repayment(repayment)
                    if not response.ok or not response.task_id:
                        raise ValueError(f"Не удалось записать возврат: {response.detail or 'No task_id'}")
                    task_ids.append(response.task_id)

                task_results = await asyncio.gather(
                    *(check_task_status(api_client, task_id) for task_id in task_ids if task_id)
                )
                if all(task_results):
                    animation_task.cancel()
                    success_message = {
                        "add_income": f"{operation_info}\n\n✅ Доход успешно добавлен",
                        "add_expense": f"{operation_info}\n\n✅ Расход успешно добавлен",
                        "borrow": f"{operation_info}\n\n✅ Записан долг и расход",
                        "repay": f"{operation_info}\n\n✅ Возврат долга"
                    }.get(intent, f"{operation_info}\n\n✅ Операция выполнена")
                    await send_success_message(
                        bot, chat_id, message_id, success_message, task_ids, state, operation_info
                    )
                else:
                    raise ValueError("Задача превысила время ожидания или завершилась с ошибкой")

            except Exception as e:
                logger.error(f"Ошибка обработки операции: {e}")
                animation_task.cancel()
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"😓 Ошибка:\n{operation_info}\n\n{e} ❌",
                    parse_mode="HTML"
                )

        else:
            logger.info(f"Пользователь {user_id} отменил операцию")
            await delete_tracked_messages(bot, state, chat_id, exclude_message_id=message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{operation_info}\n\n🚫 Операция отменена",
                parse_mode="HTML"
            )

        if "confirm" not in query.data or task_ids:
            await state.clear()
            await state.set_state(MessageState.waiting_for_ai_input)
            await bot.send_message(
                chat_id=chat_id,
                text="🔄 Выберите следующую операцию",
                reply_markup=create_start_kb()
            )

    return callback_router