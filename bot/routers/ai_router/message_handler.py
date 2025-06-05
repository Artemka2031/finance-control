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
from aiogram.types import Message, Voice, InlineKeyboardMarkup, InlineKeyboardButton
from langchain_core.tracers.langchain import log_error_once

from .agent_processor import process_agent_request
from .states import MessageState
from ...agent.agent import Agent
from ...agent.config import BACKEND_URL
from ...api_client import ApiClient
from ...utils.logging import configure_logger
from ...utils.message_utils import (
    track_messages,
    delete_tracked_messages,
    animate_processing,
    format_operation_message,
)
from ...utils.voice_messages_utils import handle_audio_message

# ------------------------------------------------------------------ #
# 1. Логгер и единый Agent                                           #
# ------------------------------------------------------------------ #
logger = configure_logger("[MESSAGE_HANDLER]", "yellow")
agent = Agent()  # один экземпляр на роутер


# ------------------------------------------------------------------ #
# 2. Вспомогательные функции                                         #
# ------------------------------------------------------------------ #
def _ensure_dict(res: Any) -> Dict[str, Any]:
    """
    Приводит результат агента к словарю.

    • dict – возвращается как есть
    • JSON-строка – парсится
    • Объект с полями .messages / .output – извлекается
    • Иное → пустой результат
    """
    if isinstance(res, dict):
        return res
    if isinstance(res, str):
        try:
            return json.loads(res)
        except json.JSONDecodeError:
            logger.warning("[MESSAGE_HANDLER] JSON-строка результата не распознана")
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
    logger.info("[MESSAGE_HANDLER] Initializing message router")

    # -------------------------------------------------------------- #
    # 3.1 Обработка текстовых запросов #ИИ                           #
    # -------------------------------------------------------------- #
    @router.message(MessageState.initial or MessageState.waiting_for_ai_input, F.text)
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
            logger.debug(f"[HANDLE_AI] Handling AI message: {input_text}, state: {await state.get_state()}")

            if not input_text:
                return await bot.send_message(chat_id=chat_id, text="🤔 Укажите запрос после #ИИ")

            # — очистка старых временных сообщений
            await delete_tracked_messages(bot, state, chat_id)
            await state.update_data(agent_state=None, input_text=input_text, timer_tasks=[])

            # — сообщение-статус
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
                logger.debug(
                    f"[HANDLE_AI] Result: messages={len(result.get('messages', []))}, "
                    f"output={len(result.get('output', []))}"
                )
                return await handle_agent_result(
                    result, bot, state, chat_id, input_text, api_client, message_id=status.message_id
                )
            except Exception as e:
                anim.cancel()
                logger.error(f"Error processing AI message: {e}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status.message_id,
                    text="❌ Ошибка обработки запроса. Попробуйте снова.",
                    parse_mode="HTML",
                )
                await state.set_state(MessageState.waiting_for_ai_input)
                return status

    # -------------------------------------------------------------- #
    # 3.2 Обработка голосовых сообщений                              #
    # -------------------------------------------------------------- #
    @router.message(MessageState.initial or MessageState.waiting_for_ai_input, F.voice)
    @track_messages
    async def handle_voice(msg: Message, state: FSMContext, bot: Bot) -> Message:
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            chat_id = msg.chat.id
            logger.debug(f"[HANDLE_AI] Handling voice, state: {await state.get_state()}")
            await delete_tracked_messages(bot, state, chat_id)
            file_id_voice = msg.voice.file_id
            text = await handle_audio_message(file_id_voice, f"audio_{file_id_voice}.ogg")
            await bot.send_message(chat_id=chat_id, text=f"🎙️ Распознанный текст: {text}", parse_mode="HTML")

            status = await bot.send_message(
                chat_id=chat_id, text="🔍 Обрабатываем голосовой запрос…", parse_mode="HTML"
            )
            anim = asyncio.create_task(animate_processing(bot, chat_id, status.message_id, "Голосовой запрос"))

            try:
                raw_result = await process_agent_request(agent, text, interactive=True)
                result = _ensure_dict(raw_result)
                anim.cancel()
                logger.debug(
                    f"[HANDLE_AI] Voice result: messages={len(result.get('messages', []))}, "
                    f"output={len(result.get('output', []))}"
                )
                return await handle_agent_result(
                    result, bot, state, chat_id, text, api_client, message_id=status.message_id
                )
            except Exception as e:
                anim.cancel()
                logger.error(f"Error processing voice message: {e}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status.message_id,
                    text="❌ Ошибка обработки голосового запроса. Попробуйте снова.",
                    parse_mode="HTML",
                )
                await state.set_state(MessageState.waiting_for_ai_input)
                return status

    # -------------------------------------------------------------- #
    # 3.3 Обработка уточнений                                         #
    # -------------------------------------------------------------- #
    @router.message(MessageState.waiting_for_clarification, ~Command(commands=["start_ai", "cancel_ai"]))
    @track_messages
    async def handle_clarification(msg: Message, state: FSMContext, bot: Bot) -> Message:
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            chat_id = msg.chat.id
            user_id = msg.from_user.id
            clarification = msg.text.strip()

            data = await state.get_data()
            agent_state = data.get("agent_state")
            original_input = data.get("input_text", "")

            logger.debug(f"[CLARIFICATION] Handling clarification: {clarification}, state: {await state.get_state()}")
            logger.debug(f"[CLARIFICATION] Agent state: {json.dumps(agent_state, ensure_ascii=False, indent=2)}")

            # — проверки наличия pending-уточнения
            if not agent_state or not agent_state.get("actions"):
                logger.warning(f"[CLARIFICATION] No agent_state or actions for user {user_id}")
                await state.clear()
                await state.update_data(messages_to_delete=[], agent_state=None, input_text="", timer_tasks=[])
                await state.set_state(MessageState.waiting_for_ai_input)
                return await bot.send_message(chat_id=chat_id, text="🤔 Начните с #ИИ")

            pending = next((a for a in agent_state["actions"] if a["needs_clarification"]), None)
            if not pending:
                logger.warning(f"[CLARIFICATION] No pending clarification for user {user_id}")
                await state.clear()
                await state.update_data(messages_to_delete=[], agent_state=None, input_text="", timer_tasks=[])
                await state.set_state(MessageState.waiting_for_ai_input)
                return await bot.send_message(chat_id=chat_id, text="🤔 Нет активных уточнений. Начните с #ИИ")

            # — принимаем текстовое уточнение
            field = pending["clarification_field"]
            if field not in ["amount", "date", "coefficient", "comment"]:
                logger.info(f"[CLARIFICATION] Field {field} requires keyboard input for user {user_id}")
                return await bot.send_message(chat_id=chat_id, text="🤔 Уточните данные через клавиатуру")

            req_idx = pending["request_index"]
            logger.info(f"{user_id=} clarified {field}: {clarification}")

            # обновляем agent_state
            agent_state["requests"][req_idx]["entities"][field] = clarification
            agent_state["requests"][req_idx]["missing"] = [
                m for m in agent_state["requests"][req_idx]["missing"] if m != field
            ]
            agent_state["messages"].append({"role": "user", "content": f"Clarified: {field}={clarification}"})

            status = await bot.send_message(chat_id=chat_id, text="🔍 Обрабатываем уточнение…", parse_mode="HTML")
            anim = asyncio.create_task(animate_processing(bot, chat_id, status.message_id, "Обрабатываем уточнение"))

            try:
                raw_result = await process_agent_request(
                    agent, original_input, interactive=True, prev_state=agent_state
                )
                result = _ensure_dict(raw_result)
                anim.cancel()
                return await handle_agent_result(
                    result, bot, state, chat_id, original_input, api_client, message_id=status.message_id
                )
            except Exception as e:
                anim.cancel()
                logger.error(f"Error processing clarification: {e}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status.message_id,
                    text="❌ Ошибка обработки уточнения. Попробуйте снова.",
                    parse_mode="HTML",
                )
                await state.set_state(MessageState.waiting_for_ai_input)
                return status

    # -------------------------------------------------------------- #
    # 3.4 Универсальный вывод результата агента                       #
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
        """Разворачивает `messages` / `output` в чате и управляет состоянием."""
        # --- страховка ---
        result = _ensure_dict(result)

        messages_to_delete = (await state.get_data()).get("messages_to_delete", [])
        logger.debug(
            f"[HANDLE_AI] Processing result: messages={len(result.get('messages', []))}, "
            f"output={len(result.get('output', []))}"
        )

        # -- есть ли уточнения? --
        has_clarifications = any(msg.get("text", "").startswith("Уточните") for msg in result.get("messages", []))
        if has_clarifications:
            await state.set_state(MessageState.waiting_for_clarification)
            logger.info(f"[HANDLE_AI] Set state to waiting_for_clarification for chat {chat_id}")
        else:
            await state.set_state(MessageState.waiting_for_ai_input)
            await state.update_data(agent_state=None, timer_tasks=[])
            logger.info(f"[HANDLE_AI] Set state to waiting_for_ai_input for chat {chat_id}, cleared agent_state")

        # -- блок «сообщения» (уточнения) --
        # -- блок «сообщения» (уточнения и аналитика) --
        for msg in result.get("messages", []):
            text = msg.get("text", "")
            keyboard_data = msg.get("keyboard", {})
            if text:
                # Клавиатура только для уточнений
                kb = None
                if has_clarifications and keyboard_data.get("inline_keyboard"):
                    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_data.get("inline_keyboard", []))
                # Разбиваем длинный текст (Telegram: max 4096 символов)
                while text:
                    chunk = text[:4096]
                    text = text[4096:]
                    sent = await bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        reply_markup=kb if not text else None,
                        parse_mode="HTML"
                    )
                    messages_to_delete.append(sent.message_id)

            # -- блок «output» (подтверждения операций) --
        for out in result.get("output", []):
            entities = out.get("entities", {})
            if not isinstance(entities, dict):
                logger.error(f"[HANDLE_AI] Invalid entities type: {type(entities)}")
                continue

            msg_text = await format_operation_message(entities, api_client)
            msg_text += "\n\nПодтвердите операцию:"

            request = next(
                (r for r in result.get("state", {}).get("requests", []) if
                 r.get("index") == out.get("request_index")),
                None
            )
            intent = request.get("intent") if request else "unknown"

            await state.set_data({
                "request_index": out.get("request_index"),
                "entities": entities,
                "intent": intent,
                "state": out.get("state"),
                "messages_to_delete": messages_to_delete,
                "input_text": input_text
            })

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Подтвердить",
                                             callback_data=f"confirm_op:{out.get('request_index')}"),
                        InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{out.get('request_index')}"),
                    ]
                ]
            )
            sent = await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=kb, parse_mode="HTML")
            messages_to_delete.append(sent.message_id)

        # -- если агент вернул «ничего» --
        if not result.get("messages") and not result.get("output"):
            logger.warning("[HANDLE_AI] Empty result from agent")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ Не удалось обработать запрос. Попробуйте снова.",
                parse_mode="HTML",
            )
            await state.set_state(MessageState.waiting_for_ai_input)
            await state.update_data(agent_state=None, timer_tasks=[])
            return await bot.send_message(chat_id=chat_id, text="✅ Обработка завершена", parse_mode="HTML")

        await state.update_data(messages_to_delete=messages_to_delete, input_text=input_text)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return await bot.send_message(chat_id=chat_id, text="✅ Обработка завершена", parse_mode="HTML")

    # -------------------------------------------------------------- #
    # 3.5 Возврат роутера                                             #
    # -------------------------------------------------------------- #
    return router