"""
Запускаем Agent и превращаем результат в Telegram-сообщения.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ...agent.agent import Agent
from ...agent.agents.serialization import serialize_messages, create_aiogram_keyboard
from ...api_client import ApiClient
from ...utils.logging import configure_logger
from ...utils.message_utils import cancel_expired_message

logger = configure_logger("[AGENT_PROCESSOR]", "cyan")


# ------------------------------------------------------------------ #
# 1. Прокси к Agent.process_request                                  #
# ------------------------------------------------------------------ #
async def process_agent_request(
        agent: Agent,
        input_text: str,
        interactive: bool = True,
        prev_state: Dict | None = None,
        selection: str | None = None,
) -> Dict:
    return await agent.process_request(
        input_text,
        interactive=interactive,
        prev_state=prev_state,
        selection=selection,
    )


# ------------------------------------------------------------------ #
# 2. Отправляем / редактируем результат                              #
# ------------------------------------------------------------------ #
async def handle_agent_result(
        result: dict,
        bot: Bot,
        state: FSMContext,
        chat_id: int,
        input_text: str,
        api_client: ApiClient,
        message_id: Optional[int] = None,
) -> Message:
    logger.info(f"handle_agent_result → chat={chat_id}")

    serialized = await serialize_messages(
        result.get("messages", []),
        api_client,
        result.get("state", {}).get("metadata", {}),
        result.get("output", []),
    )
    if not serialized:
        return await bot.send_message(chat_id, "😓 Ошибка обработки запроса")

    sent: Message | None = None
    current_msg_id = message_id  # чтоб после первой итерации сбросить
    data = await state.get_data()
    timer_tasks = data.get("timer_tasks", [])

    for idx, item in enumerate(serialized):
        text = item.get("text") or "😓 Пустое сообщение"
        kb = (
            await create_aiogram_keyboard(item["keyboard"])
            if item.get("keyboard")
            else None
        )

        # сохраняем state (нужно один раз, достаточно последнего)
        if result.get("state"):
            await state.update_data(
                agent_state=result["state"],
                input_text=input_text,
                operation_info=text,
            )

        # --- первая итерация может редактировать «ожидающее» сообщение ---
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
                logger.warning(f"Edit {current_msg_id} fail: {e}")
                sent = await bot.send_message(
                    chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
                )
            current_msg_id = None  # далее только send
        else:
            sent = await bot.send_message(
                chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
            )

        # Запускаем таймер для автоматической отмены
        if sent and kb:  # Только для сообщений с клавиатурой
            timer_task = asyncio.create_task(
                cancel_expired_message(bot, chat_id, sent.message_id, state, timeout=30)
            )
            timer_tasks.append({"message_id": sent.message_id, "task": timer_task})
            await state.update_data(timer_tasks=timer_tasks)

    # возвращаем последнее отправленное / отредактированное
    return sent
