# Bot/agent/live_test_bot/ai_router.py
from typing import Optional

from aiogram import Router, Bot, F, html
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ..agent import Agent
from ..utils import agent_logger
from ...api_client import ApiClient, CodeName
from ...keyboards.confirm import create_confirm_keyboard
from ...keyboards.start_kb import create_start_kb
from ...keyboards.utils import ConfirmOperationCallback
from ...utils.message_utils import format_operation_message


async def select_category(api_client: ApiClient, input_text: str, result: dict) -> dict:
    """Generate Telegram keyboard for category selection."""
    requests = result.get("requests", [])
    if not requests:
        agent_logger.error("Ошибка: Нет запросов для обработки.")
        return {"text": "Ошибка: Нет запросов для обработки.", "keyboard": None}

    request = requests[0]
    missing = request.get("missing", [])
    if not missing:
        agent_logger.info("Все поля заполнены, уточнение не требуется.")
        return {"text": "Все поля заполнены.", "keyboard": None}

    clarification_field = missing[0]
    agent_logger.info(f"Требуется уточнить: {clarification_field}")

    async def fetch_items(field: str, *args) -> list[CodeName]:
        if field == "chapter_code":
            return await api_client.get_sections()
        elif field == "category_code":
            return await api_client.get_categories(args[0])
        elif field == "subcategory_code":
            return await api_client.get_subcategories(args[0], args[1])
        return []

    if clarification_field == "chapter_code":
        items = await fetch_items("chapter_code")
        field_text = "раздел"
    elif clarification_field == "category_code" and request["entities"].get("chapter_code"):
        items = await fetch_items("category_code", request["entities"]["chapter_code"])
        field_text = "категорию"
    elif clarification_field == "subcategory_code" and request["entities"].get("chapter_code") and request[
        "entities"].get("category_code"):
        items = await fetch_items("subcategory_code", request["entities"]["chapter_code"],
                                  request["entities"]["category_code"])
        field_text = "подкатегорию"
    else:
        agent_logger.error(f"Неизвестное поле или отсутствуют зависимости: {clarification_field}")
        return {"text": f"Ошибка: Не удалось уточнить {clarification_field}.", "keyboard": None}

    if not items:
        agent_logger.error(f"Нет данных для поля {clarification_field}")
        return {"text": f"Ошибка: Нет доступных вариантов для {field_text}.", "keyboard": None}

    buttons = [{"text": item.name, "callback_data": f"CS:{clarification_field}={item.code}"} for item in items]
    keyboard = {
        "inline_keyboard": [buttons[i:i + 3] for i in range(0, len(buttons), 3)] +
                           [[{"text": "Отмена", "callback_data": "cancel"}]]
    }
    return {
        "text": f"Уточните {field_text} для расхода: {input_text}",
        "keyboard": keyboard
    }


def create_ai_router(bot: Bot, api_client: ApiClient):
    ai_router = Router()
    agent = Agent()

    @ai_router.message(F.text.contains("#ИИ"))
    async def handle_ai_message(message: Message, state: FSMContext, bot: Bot) -> None:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.replace("#ИИ", "").strip()
        if not input_text:
            agent_logger.warning(f"Пользователь {user_id} отправил пустое сообщение с #ИИ")
            await bot.send_message(
                chat_id=chat_id,
                text="Пожалуйста, укажите запрос после #ИИ, например: #ИИ Купил кофе за 250",
                parse_mode="HTML"
            )
            return

        agent_logger.info(f"Пользователь {user_id} отправил запрос с #ИИ: {input_text}")

        # Process request through agent
        result = await agent.process_request(input_text, interactive=True)
        await handle_agent_result(result, bot, state, chat_id, input_text)

    @ai_router.callback_query(F.data.startswith("CS:") | F.data == "cancel")
    async def handle_category_selection(query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not query.message:
            agent_logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        selection = query.data
        agent_logger.info(f"Пользователь {user_id} выбрал: {selection}")

        # Retrieve previous state from FSM
        data = await state.get_data()
        prev_state = data.get("agent_state")
        input_text = data.get("input_text", "")

        if not prev_state and selection != "cancel":
            agent_logger.error(f"Нет предыдущего состояния для пользователя {user_id}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text="Произошла ошибка: состояние утеряно. Пожалуйста, начните заново с #ИИ.",
                parse_mode="HTML"
            )
            return

        # Process selection
        result = await agent.process_request(input_text, interactive=True, selection=selection, prev_state=prev_state)
        await handle_agent_result(result, bot, state, chat_id, input_text, query.message.message_id)

    @ai_router.callback_query(ConfirmOperationCallback.filter(F.confirm))
    async def handle_confirmation(query: CallbackQuery, state: FSMContext, bot: Bot,
                                  callback_data: ConfirmOperationCallback) -> None:
        if not query.message:
            agent_logger.warning(f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}")
            return
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id

        data = await state.get_data()
        operation_info = data.get("operation_info", "Расход подтверждён")
        task_ids = data.get("task_ids", [])

        if callback_data.confirm:
            agent_logger.info(f"Пользователь {user_id} подтвердил операцию")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{operation_info}\n\n✅ Операция успешно подтверждена",
                parse_mode="HTML"
            )
        else:
            agent_logger.info(f"Пользователь {user_id} отменил операцию")
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
        messages = result.get("messages", [])
        if not messages:
            agent_logger.error(f"Нет сообщений в результате обработки для чата {chat_id}")
            await bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка при обработке запроса. Попробуйте снова.",
                parse_mode="HTML"
            )
            return

        message = messages[0]
        text = message.get("text")
        keyboard_data = message.get("keyboard")

        # Форматируем текст операции, если есть output
        if result.get("output"):
            output = result["output"][0]
            entities = output.get("entities", {})
            text = await format_operation_message(entities, api_client)
            text += "\n\nПодтвердите операцию:"
        elif not text or (result.get("requests") and any(req.get("missing") for req in result.get("requests", []))):
            # Если требуется уточнение, используем select_category
            selection_response = await select_category(api_client, input_text, result)
            text = selection_response["text"]
            keyboard_data = selection_response["keyboard"]

        keyboard = None
        if keyboard_data:
            buttons = []
            for row in keyboard_data.get("inline_keyboard", []):
                row_buttons = [
                    InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                    for btn in row
                ]
                buttons.append(row_buttons)
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        # Save state for interactive mode
        if result.get("state"):
            await state.update_data(
                agent_state=result["state"],
                input_text=input_text,
                operation_info=text,
                task_ids=[output["task_id"] for output in result["output"] if "task_id" in output]
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
            except Exception as e:
                agent_logger.warning(f"Не удалось отредактировать сообщение {message_id}: {e}")
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
                reply_markup=keyboard or create_confirm_keyboard() if result.get("output") else keyboard,
                parse_mode="HTML"
            )
            if result.get("output"):
                await state.update_data(
                    message_id=sent_message.message_id,
                    operation_info=text,
                    task_ids=[output["task_id"] for output in result["output"] if "task_id" in output]
                )

    return ai_router
