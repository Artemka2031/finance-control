# Bot/routers/ai_router/serialization.py
from typing import Dict, List

from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ...agent.utils import agent_logger
from ...api_client import ApiClient
from ...routers.ai_router.states import MessageState
from ...utils.message_utils import format_operation_message


async def fetch_keyboard_items(api_client: ApiClient, field: str, entities: Dict, request_index: int, metadata: Dict) -> List[Dict]:
    """Fetch items for keyboard based on clarification field, validated against metadata."""
    agent_logger.info(f"[SERIALIZE] Fetching keyboard items for field: {field}, request_index: {request_index}")
    agent_logger.debug(f"[SERIALIZE] Entities: {entities}")
    agent_logger.debug(f"[SERIALIZE] Metadata keys: {list(metadata.keys())}")
    items = []
    try:
        if field == "chapter_code":
            valid_codes = {
                chapter_code for chapter_code in metadata.get("expenses", {})
                if metadata["expenses"][chapter_code].get("name")
            }
            agent_logger.debug(f"[SERIALIZE] Valid chapter codes: {valid_codes}")
            items = [
                {"text": data["name"], "callback_data": f"CS:chapter_code={chapter_code}:{request_index}"}
                for chapter_code, data in metadata.get("expenses", {}).items()
                if chapter_code in valid_codes and data.get("name")
            ]
        elif field == "category_code" and entities.get("chapter_code"):
            chapter_code = entities["chapter_code"]
            valid_codes = {
                cat_code for cat_code in metadata.get("expenses", {}).get(chapter_code, {}).get("cats", {})
                if metadata["expenses"][chapter_code]["cats"][cat_code].get("name")
            }
            agent_logger.debug(f"[SERIALIZE] Valid category codes for chapter {chapter_code}: {valid_codes}")
            items = [
                {"text": data["name"], "callback_data": f"CS:category_code={cat_code}:{request_index}"}
                for cat_code, data in
                metadata.get("expenses", {}).get(chapter_code, {}).get("cats", {}).items()
                if cat_code in valid_codes and data.get("name")
            ]
        elif field == "subcategory_code" and entities.get("chapter_code") and entities.get("category_code"):
            chapter_code = entities["chapter_code"]
            category_code = entities["category_code"]
            valid_codes = {
                sub_code for sub_code in
                metadata.get("expenses", {}).get(chapter_code, {}).get("cats", {}).get(category_code, {}).get("subs", {})
                if
                metadata["expenses"][chapter_code]["cats"][category_code]["subs"][sub_code].get("name")
            }
            agent_logger.debug(f"[SERIALIZE] Valid subcategory codes for chapter {chapter_code}, category {category_code}: {valid_codes}")
            items = [
                {"text": data["name"], "callback_data": f"CS:subcategory_code={sub_code}:{request_index}"}
                for sub_code, data in
                metadata.get("expenses", {}).get(chapter_code, {}).get("cats", {}).get(category_code, {}).get("subs", {}).items()
                if sub_code in valid_codes and data.get("name")
            ]
        elif field == "creditor":
            items = [
                {"text": creditor_name, "callback_data": f"CS:creditor={creditor_name}:{request_index}"}
                for creditor_name in metadata.get("creditors", {}).keys()
                if creditor_name
            ]
            agent_logger.debug(f"[SERIALIZE] Valid creditors: {list(metadata.get('creditors', {}).keys())}")
    except Exception as e:
        agent_logger.exception(f"[SERIALIZE] Error fetching keyboard items for field {field}: {e}")
    if not items:
        agent_logger.warning(f"[SERIALIZE] No items fetched for field {field}, request_index {request_index}")
    else:
        agent_logger.debug(f"[SERIALIZE] Fetched items: {items}")
    return items


async def serialize_messages(messages: List[Dict], api_client: ApiClient, metadata: Dict, output: List[Dict] = None,
                             state: FSMContext = None) -> List[Dict]:
    """Serialize agent messages, handling clarifications and confirmations."""
    agent_logger.info(f"[SERIALIZE] Serializing {len(messages)} messages")
    serialized = []

    # Handle clarification messages
    for message in messages:
        keyboard_data = message.get("keyboard")
        if not keyboard_data:
            serialized.append(message)
            continue

        inline_keyboard = keyboard_data.get("inline_keyboard", [])
        if any(any(btn.get("callback_data", "").startswith("API:fetch:") for btn in row) for row in inline_keyboard):
            request_index = message["request_indices"][0]
            for row in inline_keyboard:
                for btn in row:
                    if btn.get("callback_data", "").startswith("API:fetch:"):
                        field = btn["callback_data"].split(":")[2]
                        break
                else:
                    continue
                break
            else:
                field = None

            if field:
                entities = message.get("request_entities", message.get("requests", [{}])[0].get("entities", {}))
                items = await fetch_keyboard_items(api_client, field, entities, request_index, metadata)
                if items:
                    keyboard = {
                        "inline_keyboard": [items[i:i + 3] for i in range(0, len(items), 3)] + [
                            [{"text": "Отмена", "callback_data": f"cancel:{request_index}"}]]
                    }
                    message["keyboard"] = keyboard
                    agent_logger.debug(f"[SERIALIZE] Generated keyboard for field {field}: {keyboard}")
                else:
                    # Если подкатегории не найдены, запрашиваем текстовый ввод
                    if field == "subcategory_code" and state:
                        message[
                            "text"] = f"Подкатегории не найдены. Введите название подкатегории для категории {entities.get('category_code')} (сумма {entities.get('amount')} рублей):"
                        message["keyboard"] = {
                            "inline_keyboard": [[{"text": "Отмена", "callback_data": f"cancel:{request_index}"}]]
                        }
                        await state.set_state(MessageState.waiting_for_text_input)
                        await state.update_data(request_index=request_index)
                    else:
                        message["keyboard"] = {
                            "inline_keyboard": [[{"text": "Отмена", "callback_data": f"cancel:{request_index}"}]]
                        }
                    agent_logger.warning(f"[SERIALIZE] Empty keyboard for field {field}, request_index {request_index}")
        serialized.append(message)

    # Handle confirmation messages from output
    if output:
        for out in output:
            if out.get("state") == "Expense:confirm":
                request_index = out["request_index"]
                entities = out["entities"]
                text = await format_operation_message(entities, api_client)
                text = text.replace("<code>", "").replace("</code>", "") + "\n\nПодтвердите операцию:"
                serialized.append({
                    "text": text,
                    "keyboard": {
                        "inline_keyboard": [
                            [
                                {"text": "✅ Подтвердить", "callback_data": f"confirm_op:{request_index}"},
                                {"text": "❌ Отменить", "callback_data": f"cancel:{request_index}"}
                            ]
                        ]
                    },
                    "request_indices": [request_index]
                })
                agent_logger.debug(f"[SERIALIZE] Added confirmation message for request_index {request_index}")

    agent_logger.info(f"[SERIALIZE] Serialized {len(serialized)} messages")
    return serialized


async def create_aiogram_keyboard(keyboard_data: Dict) -> InlineKeyboardMarkup:
    """Convert serialized keyboard data to aiogram InlineKeyboardMarkup."""
    agent_logger.info("[SERIALIZE] Creating aiogram keyboard")
    buttons = []
    for row in keyboard_data.get("inline_keyboard", []):
        row_buttons = [
            InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
            for btn in row
        ]
        buttons.append(row_buttons)
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    agent_logger.debug(f"[SERIALIZE] Created keyboard with {len(buttons)} rows")
    return keyboard


def deserialize_callback_data(callback_data: str, state: Dict) -> Dict:
    """Update agent state based on callback data with validation."""
    agent_logger.info(f"[SERIALIZE] Deserializing callback data: {callback_data}")
    if callback_data.startswith("CS:"):
        parts = callback_data.split(":")
        if len(parts) != 3:
            agent_logger.error(f"[SERIALIZE] Invalid callback_data format: {callback_data}")
            return state
        field_value = parts[1].split("=", 1)
        if len(field_value) != 2:
            agent_logger.error(f"[SERIALIZE] Invalid field format in callback_data: {callback_data}")
            return state
        field, value = field_value
        request_index = int(parts[2])
        if request_index >= len(state.get("requests", [])):
            agent_logger.error(f"[SERIALIZE] Invalid request_index {request_index} in callback_data: {callback_data}")
            return state
        # Validate value against metadata
        metadata = state.get("metadata", {})
        is_valid = False
        if field == "chapter_code":
            is_valid = value in metadata.get("expenses", {})
        elif field == "category_code":
            chapter_code = state["requests"][request_index]["entities"].get("chapter_code")
            is_valid = chapter_code and value in metadata.get("expenses", {}).get(chapter_code, {}).get("cats", {})
        elif field == "subcategory_code":
            chapter_code = state["requests"][request_index]["entities"].get("chapter_code")
            category_code = state["requests"][request_index]["entities"].get("category_code")
            is_valid = chapter_code and category_code and value in metadata.get("expenses", {}).get(chapter_code,
                                                                                                    {}).get("cats",
                                                                                                            {}).get(
                category_code, {}).get("subs", {})
        elif field == "creditor":
            is_valid = value in metadata.get("creditors", {})
        if not is_valid:
            agent_logger.error(f"[SERIALIZE] Invalid {field} value {value} in callback_data: {callback_data}")
            return state
        state["requests"][request_index]["entities"][field] = value
        if field in state["requests"][request_index]["missing"]:
            state["requests"][request_index]["missing"].remove(field)
        if field == "chapter_code" and "category_code" not in state["requests"][request_index]["missing"]:
            state["requests"][request_index]["missing"].append("category_code")
        if field == "category_code" and "subcategory_code" not in state["requests"][request_index]["missing"]:
            state["requests"][request_index]["missing"].append("subcategory_code")
        state["messages"].append({"role": "user", "content": f"Selected: {callback_data}"})
        agent_logger.debug(f"[SERIALIZE] Updated state with {field}={value} for request_index {request_index}")
    elif callback_data.startswith("cancel:"):
        request_index = int(callback_data.split(":")[1])
        if request_index < len(state.get("requests", [])):
            state["requests"].pop(request_index)
            state["messages"].append({"role": "user", "content": f"Cancelled request {request_index}"})
            agent_logger.info(f"[SERIALIZE] Cancelled request_index {request_index}")
    return state