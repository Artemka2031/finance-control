from typing import Dict, List

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..utils import agent_logger
from ...api_client import ApiClient
from ...utils.message_utils import format_operation_message


async def fetch_keyboard_items(api_client: ApiClient, field: str, entities: Dict, request_index: int, metadata: Dict) -> \
List[Dict]:
    """Fetch items for keyboard based on clarification field, validated against metadata."""
    agent_logger.info(f"[SERIALIZE] Fetching keyboard items for field: {field}, request_index: {request_index}")
    items = []
    try:
        if field == "chapter_code":
            sections = await api_client.get_sections()
            valid_codes = {chapter_code for chapter_code in metadata.get("expenses", {}) if
                           isinstance(metadata["expenses"][chapter_code], dict)}
            items = [
                {"text": section.name, "callback_data": f"CS:chapter_code={section.code}:{request_index}"}
                for section in sections if section.name and section.code in valid_codes
            ]
        elif field == "category_code" and entities.get("chapter_code"):
            categories = await api_client.get_categories(entities["chapter_code"])
            valid_codes = {
                cat_code for cat_code in metadata.get("expenses", {}).get(entities["chapter_code"], {}).get("cats", {})
                if metadata["expenses"][entities["chapter_code"]]["cats"][cat_code].get("name")
            }
            items = [
                {"text": category.name, "callback_data": f"CS:category_code={category.code}:{request_index}"}
                for category in categories if category.name and category.code in valid_codes
            ]
        elif field == "subcategory_code" and entities.get("chapter_code") and entities.get("category_code"):
            subcategories = await api_client.get_subcategories(entities["chapter_code"], entities["category_code"])
            valid_codes = {
                sub_code for sub_code in
                metadata.get("expenses", {}).get(entities["chapter_code"], {}).get("cats", {}).get(
                    entities["category_code"], {}).get("subs", {})
                if
                metadata["expenses"][entities["chapter_code"]]["cats"][entities["category_code"]]["subs"][sub_code].get(
                    "name")
            }
            items = [
                {"text": subcategory.name, "callback_data": f"CS:subcategory_code={subcategory.code}:{request_index}"}
                for subcategory in subcategories if subcategory.name and subcategory.code in valid_codes
            ]
        elif field == "creditor":
            creditors = await api_client.get_creditors()
            items = [
                {"text": creditor.name, "callback_data": f"CS:creditor={creditor.code}:{request_index}"}
                for creditor in creditors if creditor.name
            ]
    except Exception as e:
        agent_logger.exception(f"[SERIALIZE] Error fetching keyboard items for field {field}: {e}")
    if not items:
        agent_logger.warning(f"[SERIALIZE] No items fetched for field {field}, request_index {request_index}")
    return items


async def serialize_messages(messages: List[Dict], api_client: ApiClient, metadata: Dict, output: List[Dict] = None) -> \
List[Dict]:
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