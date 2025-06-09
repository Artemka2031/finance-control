# bot/routers/ai_router/message_handler.py
# -*- coding: utf-8 -*-

# ------------------------------------------------------------------ #
# 0. Импорты                                                         #
# ------------------------------------------------------------------ #
import asyncio
import json
from typing import Any, Dict

from aiogram import Router, Bot, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from agent.agent import Agent
from api_client import ApiClient
from config import BACKEND_URL
from routers.ai_router.agent_processor import process_agent_request
from routers.ai_router.states import MessageState
from utils.logging import configure_logger
from utils.message_utils import (
    track_messages,
    delete_tracked_messages,
    animate_processing,
    format_operation_message,
)
from utils.voice_messages_utils import handle_audio_message

# ------------------------------------------------------------------ #
# 1. Логгер и единый Agent                                           #
# ------------------------------------------------------------------ #
logger = configure_logger("[MESSAGE_HANDLER]", "yellow")
agent = Agent()  # singleton


# ------------------------------------------------------------------ #
# 2. Вспомогательные функции                                         #
# ------------------------------------------------------------------ #
def _ensure_dict(res: Any) -> Dict[str, Any]:
    """
    Гарантирует, что результат агента — словарь.
    """
    if isinstance(res, dict):
        return res
    if isinstance(res, str):
        try:
            return json.loads(res)
        except json.JSONDecodeError:
            logger.warning("[MESSAGE_HANDLER] JSON‑строка результата не распознана")
            return {"messages": [], "output": []}
    if hasattr(res, "messages") or hasattr(res, "output"):
        return {
            "messages": getattr(res, "messages", []),
            "output": getattr(res, "output", []),
            "state": getattr(res, "state", None),
        }
    logger.error("[MESSAGE_HANDLER] Агент вернул неподдерживаемый тип, подменяем пустым результатом")
    return {"messages": [], "output": []}


# ------------------------------------------------------------------ #
# 3. Создание роутера сообщений                                      #
# ------------------------------------------------------------------ #
def create_message_router(bot: Bot, api_client: ApiClient) -> Router:
    router = Router(name="message_router")

    # -------------------------------------------------------------- #
    # 3.1 Текстовые запросы (#ИИ)                                    #
    # -------------------------------------------------------------- #
    @router.message(MessageState.initial | MessageState.waiting_for_ai_input, F.text)
    @track_messages
    async def handle_ai_message(msg: Message, state: FSMContext, bot: Bot) -> Message:
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            chat_id = msg.chat.id
            input_text = (
                msg.text.replace("#ИИ", "")
                .replace("#ии", "")
                .replace("#AI", "")
                .replace("#ai", "")
                .strip()
            )

            if not input_text:
                return await bot.send_message(chat_id, "🤔 Укажите запрос после #ИИ")

            await delete_tracked_messages(bot, state, chat_id)
            await state.update_data(agent_state=None, input_text=input_text, timer_tasks=[])

            status = await bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Запрос:\n{input_text}\n\n⏳ Обрабатываем операцию…",
                parse_mode="HTML",
            )
            anim = asyncio.create_task(
                animate_processing(bot, chat_id, status.message_id, f"Запрос:\n{input_text}")
            )

            try:
                raw_result = await process_agent_request(agent, input_text, interactive=True)
                result = _ensure_dict(raw_result)
                anim.cancel()
                return await handle_agent_result(
                    result,
                    bot,
                    state,
                    chat_id,
                    input_text,
                    api_client,
                    message_id=status.message_id,
                )
            except Exception as e:
                anim.cancel()
                logger.exception("Error processing AI message")
                await bot.edit_message_text(
                    text="❌ Ошибка обработки запроса. Попробуйте снова.",
                    chat_id=chat_id,
                    message_id=status.message_id,
                    parse_mode="HTML",
                )
                await state.set_state(MessageState.waiting_for_ai_input)
                return status

    # -------------------------------------------------------------- #
    # 3.2 Голосовые сообщения                                        #
    # -------------------------------------------------------------- #
    @router.message(MessageState.initial | MessageState.waiting_for_ai_input, F.voice)
    @track_messages
    async def handle_voice(msg: Message, state: FSMContext, bot: Bot) -> Message:
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            chat_id = msg.chat.id
            await delete_tracked_messages(bot, state, chat_id)

            file_id_voice = msg.voice.file_id
            text = await handle_audio_message(bot, file_id_voice, f"audio_{file_id_voice}.ogg")
            await bot.send_message(chat_id, f"🎙️ Распознанный текст: {text}", parse_mode="HTML")

            status = await bot.send_message(chat_id, "🔍 Обрабатываем голосовой запрос…", parse_mode="HTML")
            anim = asyncio.create_task(animate_processing(bot, chat_id, status.message_id, "Голосовой запрос"))

            try:
                raw_result = await process_agent_request(agent, text, interactive=True)
                result = _ensure_dict(raw_result)
                anim.cancel()
                return await handle_agent_result(
                    result,
                    bot,
                    state,
                    chat_id,
                    text,
                    api_client,
                    message_id=status.message_id,
                )
            except Exception as e:
                anim.cancel()
                logger.exception("Error processing voice message")
                await bot.edit_message_text(
                    text="❌ Ошибка обработки голосового запроса. Попробуйте снова.",
                    chat_id=chat_id,
                    message_id=status.message_id,
                    parse_mode="HTML",
                )
                await state.set_state(MessageState.waiting_for_ai_input)
                return status

    # -------------------------------------------------------------- #
    # 3.3 Уточнения                                                   #
    # -------------------------------------------------------------- #
    @router.message(MessageState.waiting_for_clarification, ~Command(commands=["start_ai", "cancel_ai"]))
    @track_messages
    async def handle_clarification(msg: Message, state: FSMContext, bot: Bot) -> Message:
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            chat_id = msg.chat.id
            clarification = msg.text.strip()

            data = await state.get_data()
            agent_state = data.get("agent_state")
            original_input = data.get("input_text", "")

            if not agent_state or not agent_state.get("actions"):
                await state.clear()
                await state.set_state(MessageState.waiting_for_ai_input)
                return await bot.send_message(chat_id, "🤔 Начните с #ИИ")

            pending = next((a for a in agent_state["actions"] if a["needs_clarification"]), None)
            if not pending:
                await state.clear()
                await state.set_state(MessageState.waiting_for_ai_input)
                return await bot.send_message(chat_id, "🤔 Нет активных уточнений. Начните с #ИИ")

            field = pending["clarification_field"]
            req_idx = pending["request_index"]

            req = next(r for r in agent_state["requests"] if r["index"] == req_idx)
            req["entities"][field] = clarification
            req["missing"] = [m for m in req["missing"] if m != field]
            agent_state["messages"].append({"role": "user", "content": f"Clarified: {field}={clarification}"})

            status = await bot.send_message(chat_id, "🔍 Обрабатываем уточнение…", parse_mode="HTML")
            anim = asyncio.create_task(animate_processing(bot, chat_id, status.message_id, "Обрабатываем уточнение"))

            try:
                raw_result = await process_agent_request(
                    agent, original_input, interactive=True, prev_state=agent_state
                )
                result = _ensure_dict(raw_result)
                anim.cancel()
                return await handle_agent_result(
                    result,
                    bot,
                    state,
                    chat_id,
                    original_input,
                    api_client,
                    message_id=status.message_id,
                )
            except Exception as e:
                anim.cancel()
                logger.exception("Error processing clarification")
                await bot.edit_message_text(
                    text="❌ Ошибка обработки уточнения. Попробуйте снова.",
                    chat_id=chat_id,
                    message_id=status.message_id,
                    parse_mode="HTML",
                )
                await state.set_state(MessageState.waiting_for_ai_input)
                return status

    # -------------------------------------------------------------- #
    # 3.4 Универсальный вывод результата                              #
    # -------------------------------------------------------------- #
    async def handle_agent_result(
            result: Dict[str, Any],
            bot: Bot,
            state: FSMContext,
            chat_id: int,
            input_text: str,
            api_client: ApiClient,
            message_id: int,
    ) -> Message:
        """
        Выводит сообщения агента, клавиатуры и управляет FSM.
        """
        result = _ensure_dict(result)

        messages_to_delete = (await state.get_data()).get("messages_to_delete", [])

        has_clarifications = any(
            m.get("text", "").startswith("Уточните") for m in result.get("messages", [])
        )
        has_confirms = any(
            o.get("state", "").lower().endswith(":confirm") for o in result.get("output", [])
        )

        # --- FSM --------------------------------------------------------- #
        if has_clarifications:
            await state.set_state(MessageState.waiting_for_clarification)
        else:
            await state.set_state(MessageState.waiting_for_ai_input)

        if has_confirms:
            await state.update_data(agent_state=result.get("state"), timer_tasks=[])
        elif not has_clarifications:
            await state.update_data(agent_state=None, timer_tasks=[])

        # --- Сообщения агента ------------------------------------------- #
        for msg in result.get("messages", []):
            text = msg.get("text", "")
            if not text:
                continue

            kb_data = msg.get("keyboard", {})
            kb = None
            if has_clarifications and kb_data.get("inline_keyboard"):
                kb = InlineKeyboardMarkup(inline_keyboard=kb_data["inline_keyboard"])

            while text:
                chunk, text = text[:4096], text[4096:]
                sent = await bot.send_message(
                    chat_id,
                    chunk,
                    reply_markup=kb if not text else None,
                    parse_mode="HTML",
                )
                messages_to_delete.append(sent.message_id)

        # --- Подтверждения ---------------------------------------------- #
        for out in result.get("output", []):
            if not out.get("state", "").lower().endswith(":confirm"):
                continue

            entities = out.get("entities", {})
            req_index = out.get("request_index")

            msg_text = (
                           await format_operation_message(entities, api_client)
                       ) + "\n\nПодтвердите операцию:"

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить",
                            callback_data=f"confirm_op:{req_index}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отменить",
                            callback_data=f"cancel:{req_index}",
                        ),
                    ]
                ]
            )
            sent = await bot.send_message(chat_id, msg_text, reply_markup=kb, parse_mode="HTML")
            messages_to_delete.append(sent.message_id)

        # --- Пустой ответ ------------------------------------------------ #
        if not result.get("messages") and not result.get("output"):
            await bot.edit_message_text(
                text="❌ Не удалось обработать запрос. Попробуйте снова.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
            await state.set_state(MessageState.waiting_for_ai_input)
            await state.update_data(agent_state=None, timer_tasks=[])
            return await bot.send_message(chat_id, "✅ Обработка завершена", parse_mode="HTML")

        # --- Финальные обновления --------------------------------------- #
        await state.update_data(messages_to_delete=messages_to_delete, input_text=input_text)
        await bot.delete_message(chat_id, message_id)
        return await bot.send_message(chat_id, "✅ Обработка завершена", parse_mode="HTML")

    # -------------------------------------------------------------- #
    # 3.5 Возврат роутера                                            #
    # -------------------------------------------------------------- #
    return router
