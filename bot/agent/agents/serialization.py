"""
Сериализация «сырых» данных агента в сообщения + inline-клавиатуры.
"""

import re
from typing import Dict, List, Any

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from api_client import ApiClient
from utils.logging import configure_logger
from utils.message_utils import format_operation_message

logger = configure_logger("[SERIALIZATION]", "green")


async def fetch_keyboard_items(
        api_client: ApiClient,
        field: str,
        request: Dict,
        request_index: int,
        metadata: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Создаёт элементы клавиатуры для указанного поля."""
    logger.info(f"[SERIALIZE] fetch_keyboard_items → field={field}, req#{request_index}")

    items = []
    intent = request.get("intent", "")
    entities = request.get("entities", {})

    try:
        if field == "chapter_code":
            sections = await api_client.get_sections()
            items = [
                {"text": s.name, "callback_data": f"CS:chapter_code={s.code}:{request_index}"}
                for s in sections
            ]

        elif field == "category_code":
            if intent == "add_income":
                categories = await api_client.get_incomes()
                logger.debug(f"[SERIALIZE] Income categories fetched: {[c.name for c in categories]}")
                items = [
                    {"text": c.name, "callback_data": f"CS:category_code={c.code}:{request_index}"}
                    for c in categories
                ]
            else:
                chapter = entities.get("chapter_code", "")
                if chapter:
                    categories = await api_client.get_categories(chapter)
                    items = [
                        {"text": c.name, "callback_data": f"CS:category_code={c.code}:{request_index}"}
                        for c in categories
                    ]

        elif field == "subcategory_code":
            chapter = entities.get("chapter_code", "")
            category = entities.get("category_code", "")
            if chapter and category:
                subcategories = await api_client.get_subcategories(chapter, category)
                items = [
                    {"text": s.name, "callback_data": f"CS:subcategory_code={s.code}:{request_index}"}
                    for s in subcategories
                ]

        elif field == "creditor":
            creditors = await api_client.get_creditors()
            items = [
                {"text": c.name, "callback_data": f"CS:creditor={c.code}:{request_index}"}
                for c in creditors
            ]

    except Exception as e:
        logger.error(f"[SERIALIZE] Error fetching keyboard items for {field}: {e}")

    if not items:
        logger.warning(f"[SERIALIZE] No keyboard items fetched for {field}, req#{request_index}")
        items = [
            {"text": f"Не удалось загрузить {field}. Попробуйте позже.", "callback_data": f"cancel:{request_index}"}
        ]

    return items


async def serialize_messages(
        messages: List[Dict],
        api_client: ApiClient,
        metadata: Dict[str, Any],
        output: List[Dict] | None = None,
) -> List[Dict]:
    """
    • Превращает сообщения LLM-агента в «чистые» dict-и
    • Дорисовывает клавиатуры для уточнений
    • Добавляет confirm-сообщения для операций вида `*:confirm`
    """
    logger.info(f"[SERIALIZE] входных сообщений: {len(messages)}")
    serialized: list[Dict] = []

    output_map = {o["request_index"]: o for o in output or []}
    requests = {r["index"]: r for r in metadata.get("requests", [])}

    for msg in messages:
        text = msg.get("text", "")
        request_indices = msg.get("request_indices", [])
        keyboard = msg.get("keyboard", {"inline_keyboard": []})

        if not request_indices:
            logger.debug("[SERIALIZE] No request_indices for message, adding as is")
            serialized.append({
                "text": text.strip(),
                "keyboard": keyboard,
                "request_indices": [],
            })
            continue

        # Проверяем клавиатуру на наличие API:fetch
        for row in keyboard.get("inline_keyboard", []):
            for btn in row:
                if "API:fetch" in btn.get("text", ""):
                    api_match = re.match(r"API:fetch:(\w+):(\d+)", btn["text"])
                    if api_match:
                        field, idx = api_match.groups()
                        req_idx = int(idx)
                        request = requests.get(req_idx, {})
                        items = await fetch_keyboard_items(api_client, field, request, req_idx, metadata)
                        if items:
                            keyboard["inline_keyboard"] = [[item] for item in items]
                            keyboard["inline_keyboard"].append(
                                [{"text": "Отмена", "callback_data": f"cancel:{req_idx}"}]
                            )
                            text = re.sub(r"API:fetch:\w+:\d+", "", text).strip()
                        else:
                            logger.error(f"[SERIALIZE] Empty keyboard for API:fetch:{field}:{idx}")

        # Обрабатываем API-запросы в тексте
        for req_idx in request_indices:
            request = requests.get(req_idx, {})
            for api_match in re.finditer(r"API:fetch:(\w+):(\d+)", text):
                field, idx = api_match.groups()
                if int(idx) == req_idx:
                    items = await fetch_keyboard_items(api_client, field, request, req_idx, metadata)
                    if items:
                        keyboard["inline_keyboard"] = [[item] for item in items]
                        keyboard["inline_keyboard"].append(
                            [{"text": "Отмена", "callback_data": f"cancel:{req_idx}"}]
                        )
                        text = text.replace(api_match.group(0), "")
                    else:
                        logger.error(f"[SERIALIZE] Empty keyboard for API:fetch:{field}:{idx}")

            serialized.append({
                "text": text.strip(),
                "keyboard": keyboard,
                "request_indices": [req_idx],
            })

        # Добавляем сообщения подтверждения для операций
        for req_idx in request_indices:
            if req_idx in output_map and output_map[req_idx].get("state", "").lower().endswith(":confirm"):
                request = requests.get(req_idx, {})
                logger.debug(f"[SERIALIZE] добавлен confirm для req#{req_idx}")
                serialized.append({
                    "text": (
                                await format_operation_message(request["entities"], api_client)
                            ).replace("<code>", "").replace("</code>", "") + "\n\nПодтвердите операцию:",
                    "keyboard": {
                        "inline_keyboard": [
                            [
                                {"text": "✅ Подтвердить", "callback_data": f"confirm_op:{req_idx}"},
                                {"text": "❌ Отменить", "callback_data": f"cancel:{req_idx}"},
                            ]
                        ]
                    },
                    "request_indices": [req_idx],
                })

    logger.info(f"[SERIALIZE] итоговых сообщений: {len(serialized)}")
    return serialized


async def create_aiogram_keyboard(keyboard_data: Dict) -> InlineKeyboardMarkup:
    """Преобразует словарь клавиатуры в объект aiogram."""
    buttons: list[list[InlineKeyboardButton]] = []
    for row in keyboard_data.get("inline_keyboard", []):
        buttons.append(
            [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]) for btn in row]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def deserialize_callback_data(callback_data: str, state: Dict) -> Dict:
    """
    Обновляет состояние на основе callback-данных.
    """
    logger, logger.info(f"[SERIALIZE] deserialize: {callback_data}")
    state = state.copy()
    requests = state.get("requests", [])

    if callback_data.startswith("CS:"):
        try:
            field, rest = callback_data[3:].split("=", 1)
            value, req_idx = rest.split(":", 1)
            req_idx = int(req_idx)
            for req in requests:
                if req["index"] == req_idx:
                    req["entities"][field] = value
                    req["missing"] = [m for m in req["missing"] if m != field]
                    break
        except Exception as e:
            logger.error(f"[SERIALIZE] bad callback_data: {callback_data}, error: {e}")
            return state

        # Каскадное ожидание следующих полей
        for req in requests:
            if req["index"] == req_idx:
                if field == "chapter_code" and "category_code" not in req["missing"]:
                    req["missing"].append("category_code")
                if field == "category_code" and "subcategory_code" not in req["missing"]:
                    req["missing"].append("subcategory_code")
                break

        state["messages"].append({"role": "user", "content": f"Selected: {callback_data}"})

    elif callback_data.startswith("cancel:"):
        try:
            req_idx = int(callback_data.split(":")[1])
            state["requests"] = [r for r in requests if r["index"] != req_idx]
            state["messages"].append({"role": "user", "content": f"Cancelled request {req_idx}"})
        except Exception as e:
            logger.error(f"[SERIALIZE] bad cancel callback_data: {callback_data}, error: {e}")

    return state
