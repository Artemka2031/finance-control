from __future__ import annotations

import asyncio
import json
from typing import Optional, Dict, Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from agent.agent import Agent
from agent.agents.serialization import serialize_messages, create_aiogram_keyboard
from api_client import ApiClient
from utils.logging import configure_logger
from utils.message_utils import cancel_expired_message

logger = configure_logger("[AGENT_PROCESSOR]", "cyan")


def _normalize_result(res: Any) -> Dict[str, Any]:
    """
    Приводим всё, что может вернуть агент, к ожидаемому формату dict.
    """
    # Уже dict – выходим
    if isinstance(res, dict):
        return res

    # JSON-строка
    if isinstance(res, str):
        try:
            return json.loads(res)
        except json.JSONDecodeError:
            logger.warning("[AGENT_PROCESSOR] Не удалось разобрать JSON-строку, возвращённую агентом")
            return {"messages": [], "output": []}

    # Объект AgentState (fallback)
    if hasattr(res, "output") and isinstance(res.output, dict):
        return res.output

    logger.error("[AGENT_PROCESSOR] Агент вернул неподдерживаемый тип, замещаем пустым результатом")
    return {"messages": [], "output": []}


async def process_agent_request(
        agent: Agent,
        input_text: str,
        interactive: bool = True,
        prev_state: Dict | None = None,
        selection: str | None = None,
) -> Dict:
    """
    Обёртка над `agent.process_request`, всегда выдаёт dict.
    """
    logger.debug(f"[AGENT_PROCESSOR] Processing request: input={input_text[:50]}, interactive={interactive}")
    raw_result = await agent.process_request(
        input_text,
        interactive=interactive,
        prev_state=prev_state,
        selection=selection,
    )
    result: Dict[str, Any] = _normalize_result(raw_result)
    logger.debug(
        f"[AGENT_PROCESSOR] Result: messages={len(result.get('messages', []))}, "
        f"output={len(result.get('output', []))}"
    )
    return result


async def handle_agent_result(
        result: dict,
        bot: Bot,
        state: FSMContext,
        chat_id: int,
        input_text: str,
        api_client: ApiClient,
        message_id: Optional[int] = None,
) -> Message:
    """
    Универсальный вывод результатов агента в чат.
    """
    logger.info(f"[AGENT_PROCESSOR] Handling result for chat={chat_id}, input={input_text[:50]}")
    logger.debug(f"[AGENT_PROCESSOR] Result content: {json.dumps(result, ensure_ascii=False, indent=2)}")

    serialized = await serialize_messages(
        result.get("messages", []),
        api_client,
        result.get("state", {}).get("metadata", {}),
        result.get("output", []),
    )
    if not serialized:
        logger.warning("[AGENT_PROCESSOR] No serialized messages")
        return await bot.send_message(chat_id, "😓 Ошибка обработки запроса")

    sent: Message | None = None
    current_msg_id = message_id
    data = await state.get_data()
    timer_tasks = data.get("timer_tasks", [])

    for item in serialized:
        text = item.get("text") or "😓 Пустое сообщение"
        kb = await create_aiogram_keyboard(item["keyboard"]) if item.get("keyboard") else None

        # сохраняем state
        if result.get("state"):
            await state.update_data(
                agent_state=result["state"],
                input_text=input_text,
                operation_info=text,
            )

        # редактируем или отправляем
        if current_msg_id:
            try:
                sent = await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=current_msg_id,
                    text=text,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"[AGENT_PROCESSOR] Edit {current_msg_id} failed: {e}")
                sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
            current_msg_id = None
        else:
            sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")

        # таймер для сообщений с клавиатурой
        if sent and kb:
            timer_task = asyncio.create_task(
                cancel_expired_message(bot, chat_id, sent.message_id, state, timeout=30)
            )
            timer_tasks.append({"message_id": sent.message_id, "task": timer_task})
            await state.update_data(timer_tasks=timer_tasks)

    return sent
