"""
Message-handler ветки #ИИ.

Исправления:
* никаких изменений в логике, только сохранение корректной версии,
  использующей именованные аргументы в bot.edit_message_text.
"""

import asyncio

from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Voice

from .states import MessageState
from .agent_processor import process_agent_request, handle_agent_result
from ...agent.agent import Agent
from ...api_client import ApiClient
from ...utils.message_utils import (
    track_messages,
    delete_tracked_messages,
    animate_processing,
)
from ...utils.logging import configure_logger

logger = configure_logger("[MESSAGE_HANDLER]", "yellow")


def create_message_router(bot: Bot, api_client: ApiClient) -> Router:
    router = Router()
    agent = Agent()

    # ------------------------------------------------------------------ #
    # 1. Текстовый запрос с #ИИ                                          #
    # ------------------------------------------------------------------ #
    @router.message(MessageState.waiting_for_ai_input, F.text.contains("#ИИ"))
    @track_messages
    async def handle_ai_message(msg: Message, state: FSMContext, bot: Bot) -> Message:
        chat_id = msg.chat.id
        input_text = msg.text.replace("#ИИ", "").strip()

        if not input_text:
            return await bot.send_message(chat_id, "🤔 Укажите запрос после #ИИ")

        await delete_tracked_messages(bot, state, chat_id)
        await state.set_state(MessageState.waiting_for_clarification)

        status = await bot.send_message(
            chat_id,
            f"🔍 Запрос:\n{input_text}\n\n⏳ Обрабатываем операцию…",
            parse_mode="HTML",
        )
        anim = asyncio.create_task(
            animate_processing(bot, chat_id, status.message_id, f"Запрос:\n{input_text}")
        )

        try:
            result = await process_agent_request(agent, input_text, interactive=True)
        finally:
            anim.cancel()

        return await handle_agent_result(
            result, bot, state, chat_id, input_text, api_client, message_id=status.message_id
        )

    # ------------------------------------------------------------------ #
    # 2. Голосовое сообщение                                             #
    # ------------------------------------------------------------------ #
    @router.message(MessageState.waiting_for_ai_input, F.voice)
    @track_messages
    async def handle_voice(msg: Voice, state: FSMContext, bot: Bot) -> Message:
        chat_id = msg.chat.id
        await delete_tracked_messages(bot, state, chat_id)
        await state.set_state(MessageState.waiting_for_clarification)

        text = "Купил кофе за 250 рублей"  # заглушка
        await bot.send_message(chat_id, f"🎙️ Распознанный текст: {text}", parse_mode="HTML")

        status = await bot.send_message(chat_id, "🔍 Обрабатываем голосовой запрос…", parse_mode="HTML")
        anim = asyncio.create_task(animate_processing(bot, chat_id, status.message_id, "Голосовой запрос"))

        try:
            result = await process_agent_request(agent, text, interactive=True)
        finally:
            anim.cancel()

        return await handle_agent_result(
            result, bot, state, chat_id, text, api_client, message_id=status.message_id
        )

    # ------------------------------------------------------------------ #
    # 3. Уточнения                                                       #
    # ------------------------------------------------------------------ #
    @router.message(MessageState.waiting_for_clarification, F.text)
    @track_messages
    async def handle_clarification(msg: Message, state: FSMContext, bot: Bot) -> Message:
        chat_id = msg.chat.id
        user_id = msg.from_user.id
        clarification = msg.text.strip()

        data = await state.get_data()
        agent_state = data.get("agent_state")
        original_input = data.get("input_text", "")

        if not agent_state or not agent_state.get("actions"):
            await state.set_state(MessageState.waiting_for_ai_input)
            return await bot.send_message(chat_id, "🤔 Начните с #ИИ")

        pending = next((a for a in agent_state["actions"] if a["needs_clarification"]), None)
        if not pending or pending["clarification_field"] not in ["amount", "date", "coefficient", "comment"]:
            return await bot.send_message(chat_id, "🤔 Уточните данные через клавиатуру")

        field = pending["clarification_field"]
        req_idx = pending["request_index"]
        logger.info(f"{user_id=} уточнил {field}: {clarification}")

        agent_state["requests"][req_idx]["entities"][field] = clarification
        agent_state["requests"][req_idx]["missing"] = [
            m for m in agent_state["requests"][req_idx]["missing"] if m != field
        ]
        agent_state["messages"].append({"role": "user", "content": f"Clarified: {field}={clarification}"})

        status = await bot.send_message(chat_id, "🔍 Обрабатываем уточнение…", parse_mode="HTML")
        anim = asyncio.create_task(animate_processing(bot, chat_id, status.message_id, "Обрабатываем уточнение"))

        try:
            result = await process_agent_request(agent, original_input, interactive=True, prev_state=agent_state)
        finally:
            anim.cancel()

        return await handle_agent_result(
            result, bot, state, chat_id, original_input, api_client, message_id=status.message_id
        )

    # ------------------------------------------------------------------ #
    return router
