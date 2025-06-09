# bot/routers/ai_router/callback_handler.py
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------ #
# 0. Импорты                                                         #
# ------------------------------------------------------------------ #
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Router, Bot, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from agent.agent import Agent
from agent.agents.serialization import deserialize_callback_data
from api_client import ApiClient, ExpenseIn, IncomeIn, CreditorIn
from keyboards.start_kb import create_start_kb
from routers.ai_router.agent_processor import process_agent_request, handle_agent_result
from routers.ai_router.states import MessageState
from utils.logging import configure_logger
from utils.message_utils import (
    track_messages,
    delete_tracked_messages,
    animate_processing,
    format_operation_message,
    check_task_status,
    send_success_message,
)

logger = configure_logger("[CALLBACK_HANDLER]", "magenta")


# ------------------------------------------------------------------ #
# 1. Вспомогательные функции                                         #
# ------------------------------------------------------------------ #
def _safe_state(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Возвращает `agent_state` как словарь.
    Если в хранилище лежит `None`, подменяет его на `{}`.
    """
    state_val = data.get("agent_state")
    return state_val if isinstance(state_val, dict) else {}


# ------------------------------------------------------------------ #
# 2. Создание роутера                                                #
# ------------------------------------------------------------------ #
def create_callback_router(bot: Bot, api_client: ApiClient) -> Router:
    router = Router()
    agent = Agent()

    # ------------------------------------------------------------------ #
    # 2.1. Выбор категории или отмена                                    #
    # ------------------------------------------------------------------ #
    @router.callback_query(F.data.startswith("CS:") | F.data.startswith("cancel:"))
    @track_messages
    async def handle_category_selection(
            query: CallbackQuery, state: FSMContext, bot: Bot
    ) -> Optional[Message]:
        if not query.message:  # safety‑check
            logger.warning(f"CallbackQuery без message от {query.from_user.id}")
            return None

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        selection = query.data

        logger.info(f"{user_id=}: выбрал {selection=}")

        # отменяем таймеры
        data = await state.get_data()
        for t in data.get("timer_tasks", []):
            t["task"].cancel()
        await state.update_data(timer_tasks=[])

        # previous agent_state
        data = await state.get_data()
        prev_state = _safe_state(data)
        input_text = data.get("input_text", "")

        # ---------- 2.1.a Отмена уточнения ---------- #
        if selection.startswith("cancel:"):
            prev_state = deserialize_callback_data(selection, prev_state)
            await delete_tracked_messages(bot, state, chat_id, exclude_message_id=message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ Уточнение отменено",
                parse_mode="HTML",
            )
            # если запросов больше нет — сбрасываемся
            if not prev_state.get("requests"):
                await state.clear()
                await state.set_state(MessageState.waiting_for_ai_input)
                return await bot.send_message(
                    chat_id=chat_id,
                    text="🔄 Выберите следующую операцию",
                    reply_markup=create_start_kb(),
                )

            processing = await bot.send_message(
                chat_id=chat_id,
                text="🔍 Обрабатываем отмену…",
                parse_mode="HTML",
            )
            result = await process_agent_request(
                agent, input_text, interactive=True, selection=selection, prev_state=prev_state
            )
            return await handle_agent_result(
                result, bot, state, chat_id, input_text, api_client, message_id=processing.message_id
            )

        # ---------- 2.1.b Обычный выбор категории ---------- #
        if not prev_state:
            logger.error(f"state потерян у {user_id}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="😓 Ошибка: состояние утеряно. Начните заново с #ИИ",
                parse_mode="HTML",
            )
            return None

        prev_state = deserialize_callback_data(selection, prev_state)
        processing = await bot.send_message(chat_id=chat_id, text="🔍 Обрабатываем выбор…", parse_mode="HTML")
        result = await process_agent_request(
            agent, input_text, interactive=True, selection=selection, prev_state=prev_state
        )
        return await handle_agent_result(
            result, bot, state, chat_id, input_text, api_client, message_id=processing.message_id
        )

    # ------------------------------------------------------------------ #
    # 2.2. Подтверждение / отмена операции                                #
    # ------------------------------------------------------------------ #
    @router.callback_query(F.data.startswith("confirm_op:"))
    @track_messages
    async def handle_confirmation(
            query: CallbackQuery, state: FSMContext, bot: Bot
    ) -> Optional[Message]:
        if not query.message:
            return None

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        request_index = int(query.data.split(":")[1])

        logger.info(f"{user_id=}: подтвердил запрос #{request_index}")

        # отменяем таймеры
        data = await state.get_data()
        for t in data.get("timer_tasks", []):
            t["task"].cancel()
        await state.update_data(timer_tasks=[])

        await state.set_state(MessageState.confirming_operation)

        # ------------------------------------------------------------------ #
        # ❶  Достаём нужный запрос из agent_state.requests                   #
        # ------------------------------------------------------------------ #
        agent_state = _safe_state(data)
        req = next(
            (r for r in agent_state.get("requests", []) if r.get("index") == request_index),
            None,
        )
        if not req:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="😓 Ошибка: запрос не найден",
                parse_mode="HTML",
            )
            return query.message

        intent = req["intent"]
        entities = req["entities"]
        operation_info = await format_operation_message(entities, api_client)

        # ------------------------------------------------------------------ #
        # ❷  Ставим статус «подтверждаем…» и анимацию                        #
        # ------------------------------------------------------------------ #
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="⏳ Подтверждаем операцию…",
            parse_mode="HTML",
        )
        animation_task = asyncio.create_task(
            animate_processing(bot, chat_id, message_id, operation_info)
        )

        task_ids: list[str] = []
        try:
            # нормализуем дату
            date_str = entities["date"]
            date_obj = datetime.strptime(date_str, "%d.%m.%y" if len(date_str) == 8 else "%d.%m.%Y")
            date_str = date_obj.strftime("%d.%m.%Y")

            # ------------------------------------------------------------------ #
            # ❸  INTENT‑специфическая логика                                     #
            # ------------------------------------------------------------------ #
            if intent == "add_income":
                dto = IncomeIn(
                    date=date_str,
                    cat_code=entities["category_code"],
                    amount=float(entities["amount"]),
                    comment=entities["comment"],
                )
                resp = await api_client.add_income(dto)
                if not resp.ok or not resp.task_id:
                    raise RuntimeError(resp.detail or "No task id")
                task_ids.append(resp.task_id)

            elif intent == "add_expense":
                dto = ExpenseIn(
                    date=date_str,
                    sec_code=entities["chapter_code"],
                    cat_code=entities["category_code"],
                    sub_code=entities["subcategory_code"],
                    amount=float(entities["amount"]),
                    comment=entities["comment"],
                )
                resp = await api_client.add_expense(dto)
                if not resp.ok or not resp.task_id:
                    raise RuntimeError(resp.detail or "No task id")
                task_ids.append(resp.task_id)

            elif intent == "borrow":
                dto_exp = ExpenseIn(
                    date=date_str,
                    sec_code=entities["chapter_code"],
                    cat_code=entities["category_code"],
                    sub_code=entities["subcategory_code"],
                    amount=float(entities["amount"]),
                    comment=entities["comment"],
                )
                dto_bor = CreditorIn(
                    date=date_str,
                    cred_code=entities["creditor"],
                    amount=float(entities["amount"]),
                    comment=entities["comment"],
                )
                resp_exp = await api_client.add_expense(dto_exp)
                resp_bor = await api_client.record_borrowing(dto_bor)
                if not all((resp_exp.ok, resp_exp.task_id, resp_bor.ok, resp_bor.task_id)):
                    raise RuntimeError("Ошибка записи долга и расхода")
                task_ids.extend([resp_exp.task_id, resp_bor.task_id])

            elif intent == "repay":
                dto = CreditorIn(
                    date=date_str,
                    cred_code=entities["creditor"],
                    amount=float(entities["amount"]),
                    comment=entities["comment"],
                )
                resp = await api_client.record_repayment(dto)
                if not resp.ok or not resp.task_id:
                    raise RuntimeError(resp.detail or "No task id")
                task_ids.append(resp.task_id)

            # ------------------------------------------------------------------ #
            # ❹  Ждём завершения фоновых задач                                  #
            # ------------------------------------------------------------------ #
            results = await asyncio.gather(*(check_task_status(api_client, tid) for tid in task_ids))
            if not all(results):
                raise RuntimeError("Операция не завершилась успешно")

            # ------------------------------------------------------------------ #
            # ❺  Успех                                                          #
            # ------------------------------------------------------------------ #
            animation_task.cancel()
            success_text = {
                "add_income": "✅ Доход успешно добавлен",
                "add_expense": "✅ Расход успешно добавлен",
                "borrow": "✅ Записан долг и расход",
                "repay": "✅ Возврат долга",
            }.get(intent, "✅ Операция выполнена")

            await send_success_message(
                bot,
                chat_id,
                message_id,
                f"{operation_info}\n\n{success_text}",
                task_ids,
                state,
                operation_info,
            )
            # чистим таймеры для этого сообщения
            timer_tasks = data.get("timer_tasks", [])
            timer_tasks = [t for t in timer_tasks if t["message_id"] != message_id]
            await state.update_data(timer_tasks=timer_tasks)
            return query.message

        except Exception as err:
            animation_task.cancel()
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"😓 Ошибка:\n{operation_info}\n\n{err} ❌",
                parse_mode="HTML",
            )
            return query.message  # чтобы трекер не ругался

    # ------------------------------------------------------------------ #
    # 2.3. Возврат роутера                                               #
    # ------------------------------------------------------------------ #
    return router
