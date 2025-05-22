import asyncio
import random
from typing import Optional, Dict
from datetime import datetime
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Chat

from ...agent.agent import Agent
from ...agent.agents.serialization import serialize_messages, create_aiogram_keyboard
from ...api_client import ApiClient
from ...utils.logging import configure_logger
from ...utils.message_utils import format_operation_message

logger = configure_logger("[AGENT_PROCESSOR]", "cyan")


async def process_agent_request(agent: Agent, input_text: str, interactive: bool = True,
                                prev_state: Dict = None, selection: str = None, bot: Bot = None,
                                chat_id: int = None, message_id: int = None) -> Dict:
    """Обрабатывает запрос агента."""
    # Устанавливаем параметры для анимации
    agent.bot = bot
    agent.chat_id = chat_id
    agent.message_id = message_id
    result = await agent.process_request(
        input_text,
        interactive=interactive,
        prev_state=prev_state,
        selection=selection
    )
    return result


async def animate_agent_processing(bot: Bot, chat_id: int, message_id: int, intent: str = None) -> None:
    """Отображает вариативную анимацию обработки агента."""
    general_stages = [
        "🔍 Анализируем ваш запрос...",
        "🧠 Разбираем детали...",
        "📋 Проверяем информацию...",
        "🔎 Изучаем контекст...",
        "💡 Обрабатываем данные...",
        "🛠️ Собираем ответ..."
    ]
    intent_map = {
        "add_income": [
            "💰 Распознаём доход...",
            "💸 Учитываем поступление...",
            "📈 Добавляем доход..."
        ],
        "add_expense": [
            "🛒 Учитываем расход...",
            "💳 Записываем трату...",
            "🛍️ Обрабатываем покупку..."
        ],
        "borrow": [
            "🤝 Оформляем долг...",
            "📝 Регистрируем заём...",
            "💶 Записываем кредит..."
        ],
        "repay": [
            "✅ Возвращаем долг...",
            "💸 Погашаем заём...",
            "✔️ Закрываем долг..."
        ]
    }

    stages = intent_map.get(intent, []) + random.sample(general_stages, k=min(3, len(general_stages)))
    random.shuffle(stages)

    for stage in stages[:4]:  # Ограничим до 4 этапов для скорости
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=stage,
                parse_mode="HTML"
            )
            await asyncio.sleep(0.8)  # Ускорили анимацию
        except Exception as e:
            logger.warning(f"Не удалось анимировать обработку агента: {e}")
            break


async def handle_agent_result(result: dict, bot: Bot, state: FSMContext, chat_id: int,
                              input_text: str, api_client: ApiClient, message_id: Optional[int] = None) -> Message:
    """Обрабатывает результат агента и отправляет отформатированный ответ."""
    logger.info(f"Обработка результата агента для чата {chat_id}")
    messages = result.get("messages", [])
    output = result.get("output", [])

    serialized_messages = await serialize_messages(
        messages,
        api_client,
        result.get("state", {}).get("metadata", {}),
        output
    )
    logger.debug(f"Сериализовано {len(serialized_messages)} сообщений")

    if not serialized_messages:
        logger.error(f"Нет сообщений в результате для чата {chat_id}")
        return await bot.send_message(
            chat_id=chat_id,
            text="😓 Ошибка обработки запроса. Попробуйте снова!",
            parse_mode="HTML"
        )

    sent_message = None
    for message in serialized_messages:
        text = message.get("text", "")
        keyboard_data = message.get("keyboard")
        keyboard = await create_aiogram_keyboard(keyboard_data) if keyboard_data else None
        request_indices = message.get("request_indices", [])

        if not text:
            logger.error(f"Пустой текст сообщения для чата {chat_id}, request_indices: {request_indices}")
            text = "😓 Ошибка: пустое сообщение. Попробуйте снова!"

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
                chat = await bot.get_chat(chat_id)
                sent_message = Message(
                    message_id=message_id,
                    chat=chat,
                    text=text,
                    date=datetime.now()  # Добавляем поле date
                )
                logger.info(f"Отредактировано сообщение {message_id} с текстом: {text[:50]}...")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {message_id}: {e}")
                sent_message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                logger.info(f"Отправлено новое сообщение {sent_message.message_id} с текстом: {text[:50]}...")
        else:
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            logger.info(f"Отправлено сообщение {sent_message.message_id} с текстом: {text[:50]}...")
            if output:
                await state.update_data(
                    message_id=sent_message.message_id,
                    operation_info=text,
                    task_ids=[out["task_id"] for out in output if "task_id" in out]
                )

    return sent_message
