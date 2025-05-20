# Bot/agent/live_test_bot/ai_router.py
import json
from typing import Optional

from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from ..agent import Agent
from ..utils import agent_logger
from ...api_client import ApiClient, ExpenseIn
from ..agents.serialization import serialize_messages, create_aiogram_keyboard, deserialize_callback_data
from ...keyboards.start_kb import create_start_kb


async def format_operation_message(data: dict, api_client: ApiClient, include_amount: bool = True) -> str:
    """Format operation message, skipping empty fields."""
    date = data.get("date", "")
    wallet = data.get("wallet", "")
    wallet_name = "Проект" if wallet == "project" else wallet
    sec_code = data.get("chapter_code", "")
    cat_code = data.get("category_code", "")
    sub_code = data.get("subcategory_code", "")
    amount = data.get("amount", "0") if include_amount else None
    comment = data.get("comment", "")

    section_name = category_name = subcategory_name = ""
    try:
        if sec_code:
            sections = await api_client.get_sections()
            section_name = next((sec.name for sec in sections if sec.code == sec_code), "")
        if cat_code and sec_code:
            categories = await api_client.get_categories(sec_code)
            category_name = next((cat.name for cat in categories if cat.code == cat_code), "")
        if sub_code and sec_code and cat_code:
            subcategories = await api_client.get_subcategories(sec_code, cat_code)
            subcategory_name = next((sub.name for sub in subcategories if sub.code == sub_code), "")
        agent_logger.debug(
            f"[FORMAT] Retrieved names: section={section_name}, category={category_name}, subcategory={subcategory_name}")
    except Exception as e:
        agent_logger.warning(f"[FORMAT] Error retrieving category names: {e}")

    message_lines = []
    if date:
        message_lines.append(f"Дата: 🗓️ {date}")
    if wallet_name:
        message_lines.append(f"Кошелёк: 💸 {wallet_name}")
    if section_name:
        message_lines.append(f"Раздел: 📕 {section_name}")
    if category_name:
        message_lines.append(f"Категория: 🏷️ {category_name}")
    if subcategory_name:
        message_lines.append(f"Подкатегория: 🏷️ {subcategory_name}")
    if amount is not None and amount != "0":
        message_lines.append(f"Сумма: 💰 {amount} ₽")
    if comment:
        message_lines.append(f"Комментарий: 💬 {comment}")

    return "\n".join(message_lines)


def create_ai_router(bot: Bot, api_client: ApiClient):
    ai_router = Router()
    agent = Agent()

    @ai_router.message(F.text.contains("#ИИ"))
    async def handle_ai_message(message: Message, state: FSMContext, bot: Bot) -> None:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.replace("#ИИ", "").strip()
        if not input_text:
            agent_logger.warning(f"[AI_ROUTER] Пользователь {user_id} отправил пустое сообщение с #ИИ")
            await bot.send_message(
                chat_id=chat_id,
                text="Пожалуйста, укажите запрос после #ИИ, например: #ИИ Купил кофе за 250",
                parse_mode="HTML"
            )
            return

        agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} отправил запрос с #ИИ: {input_text}")

        # Process request through agent
        result = await agent.process_request(input_text, interactive=True)
        await handle_agent_result(result, bot, state, chat_id, input_text)

    @ai_router.callback_query(F.data.startswith("CS:") | F.data.startswith("cancel:"))
    async def handle_category_selection(query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not query.message:
            agent_logger.warning(f"[AI_ROUTER] Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        selection = query.data
        agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} выбрал: {selection}")

        # Retrieve previous state from FSM
        data = await state.get_data()
        prev_state = data.get("agent_state")
        input_text = data.get("input_text", "")

        if not prev_state and not selection.startswith("cancel:"):
            agent_logger.error(f"[AI_ROUTER] Нет предыдущего состояния для пользователя {user_id}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text="Произошла ошибка: состояние утеряно. Пожалуйста, начните заново с #ИИ.",
                parse_mode="HTML"
            )
            return

        # Handle cancellation
        if selection.startswith("cancel:"):
            request_index = int(selection.split(":")[1])
            agent_logger.info(
                f"[AI_ROUTER] Пользователь {user_id} отменил уточнение для request_index: {request_index}")
            prev_state = deserialize_callback_data(selection, prev_state)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
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
                return
            result = await agent.process_request(input_text, interactive=True, selection=selection,
                                                 prev_state=prev_state)
            await handle_agent_result(result, bot, state, chat_id, input_text, query.message.message_id)
            return

        # Handle category selection
        prev_state = deserialize_callback_data(selection, prev_state)
        result = await agent.process_request(input_text, interactive=True, selection=selection, prev_state=prev_state)
        await handle_agent_result(result, bot, state, chat_id, input_text, query.message.message_id)

    @ai_router.callback_query(F.data.startswith("confirm_op:"))
    async def handle_confirmation(query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not query.message:
            agent_logger.warning(f"[AI_ROUTER] Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        request_index = int(query.data.split(":")[1])

        data = await state.get_data()
        operation_info = data.get("operation_info", "Расход подтверждён")
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
            # Send expense to API
            expense = ExpenseIn(
                date=request["entities"]["date"],
                sec_code=request["entities"]["chapter_code"],
                cat_code=request["entities"]["category_code"],
                sub_code=request["entities"]["subcategory_code"],
                amount=float(request["entities"]["amount"]),
                comment=request["entities"].get("comment", "")
            )
            response = await api_client.add_expense(expense)
            if response.ok:
                agent_logger.info(f"[AI_ROUTER] Расход добавлен, task_id: {response.task_id}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{operation_info}\n\n✅ Операция успешно подтверждена",
                    parse_mode="HTML"
                )
            else:
                agent_logger.error(f"[AI_ROUTER] Не удалось добавить расход: {response.detail}")
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"Ошибка при добавлении расхода: {response.detail}",
                    parse_mode="HTML"
                )
        else:
            agent_logger.info(f"[AI_ROUTER] Пользователь {user_id} отменил операцию")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{operation_info}\n\n🚫 Операция отменена",
                parse_mode="HTML"
            )

        await state.clear()
        await bot.send_message(
            chat_id=chat_id,
            text="Выберите следующую операцию: 🔄",
            reply_markup=create_start_kb()
        )

    async def handle_agent_result(result: dict, bot: Bot, state: FSMContext, chat_id: int, input_text: str,
                                  message_id: Optional[int] = None) -> None:
        """Handle the result from agent and send appropriate response."""
        agent_logger.info(f"[AI_ROUTER] Handling agent result for chat {chat_id}")
        messages = result.get("messages", [])
        output = result.get("output", [])

        # Serialize messages and confirmations
        serialized_messages = await serialize_messages(
            messages,
            api_client,
            result.get("state", {}).get("metadata", {}),
            output
        )
        agent_logger.debug(f"[AI_ROUTER] Serialized {len(serialized_messages)} messages")

        if not serialized_messages:
            agent_logger.error(f"[AI_ROUTER] Нет сообщений в результате обработки для чата {chat_id}")
            await bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка при обработке запроса. Попробуйте снова.",
                parse_mode="HTML"
            )
            return

        for message in serialized_messages:
            text = message.get("text", "")
            keyboard_data = message.get("keyboard")
            keyboard = await create_aiogram_keyboard(keyboard_data) if keyboard_data else None
            request_indices = message.get("request_indices", [])

            if not text:
                agent_logger.error(
                    f"[AI_ROUTER] Пустой текст сообщения для чата {chat_id}, request_indices: {request_indices}")
                text = "Произошла ошибка: пустое сообщение. Попробуйте снова."

            # Save state for interactive mode
            if result.get("state"):
                await state.update_data(
                    agent_state=result["state"],
                    input_text=input_text,
                    operation_info=text,
                    task_ids=[out["task_id"] for out in output if "task_id" in out]
                )

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
                except Exception as e:
                    agent_logger.warning(f"[AI_ROUTER] Не удалось отредактировать сообщение {message_id}: {e}")
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
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

    return ai_router
