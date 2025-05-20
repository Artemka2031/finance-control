# Bot/agent/agents/response.py
import json

from ...api_client import ApiClient
from ..config import BACKEND_URL
from ..utils import AgentState, agent_logger, section_cache, category_cache, subcategory_cache


async def response_agent(state: AgentState) -> AgentState:
    """Generate response messages or final output."""
    agent_logger.info("[RESPONSE] Entering response_agent")
    if not state.actions:
        agent_logger.info("[RESPONSE] No actions to process")
        return state

    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            messages = []
            output = []
            for action in state.actions:
                request = state.requests[action["request_index"]]
                entities = request["entities"]
                missing = request["missing"]

                if not action.get("needs_clarification"):
                    if action.get("ready_for_output"):
                        # Get category and subcategory names for output
                        category_name = "Unknown"
                        subcategory_name = "Unknown"
                        if entities.get("chapter_code") and entities.get("category_code"):
                            categories = category_cache.get(entities["chapter_code"])
                            if not categories:
                                categories = await api_client.get_categories(entities["chapter_code"])
                                category_cache[entities["chapter_code"]] = categories
                                agent_logger.info(f"[RESPONSE] Fetched {len(categories)} categories")
                                agent_logger.debug(
                                    f"[RESPONSE] Fetched categories for {entities['chapter_code']}: {[{'code': cat.code, 'name': cat.name} for cat in categories]}")
                            category_name = next(
                                (cat.name for cat in categories if cat.code == entities["category_code"]), "Unknown")
                        if entities.get("chapter_code") and entities.get("category_code") and entities.get(
                                "subcategory_code"):
                            cat_key = f"{entities['chapter_code']}/{entities['category_code']}"
                            subcategories = subcategory_cache.get(cat_key)
                            if not subcategories:
                                subcategories = await api_client.get_subcategories(entities["chapter_code"],
                                                                                   entities["category_code"])
                                subcategory_cache[cat_key] = subcategories
                                agent_logger.info(f"[RESPONSE] Fetched {len(subcategories)} subcategories")
                                agent_logger.debug(
                                    f"[RESPONSE] Fetched subcategories for {cat_key}: {[{'code': sub.code, 'name': sub.name} for sub in subcategories]}")
                            subcategory_name = next(
                                (sub.name for sub in subcategories if sub.code == entities["subcategory_code"]),
                                "Unknown")
                        messages.append({
                            "text": f"Расход {entities['amount']} на {category_name} ({subcategory_name}) записан.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        output.append({
                            "request_index": action["request_index"],
                            "entities": entities,
                            "state": "Expense:confirm"
                        })
                        continue

                clarification_field = action["clarification_field"]
                buttons = []
                if clarification_field == "chapter_code":
                    if not section_cache:
                        section_cache.extend(await api_client.get_sections())
                        agent_logger.info(f"[RESPONSE] Fetched {len(section_cache)} sections")
                        agent_logger.debug(
                            f"[RESPONSE] Fetched sections: {[{'code': sec.code, 'name': sec.name} for sec in section_cache]}")
                    if not section_cache:
                        messages.append({
                            "text": "Ошибка: нет доступных разделов.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        continue
                    buttons = [
                        {"text": sec.name, "callback_data": f"CS:chapter_code={sec.code}"}
                        for sec in section_cache if sec.name
                    ]
                elif clarification_field == "category_code" and entities.get("chapter_code"):
                    categories = category_cache.get(entities["chapter_code"])
                    if not categories:
                        categories = await api_client.get_categories(entities["chapter_code"])
                        category_cache[entities["chapter_code"]] = categories
                        agent_logger.info(f"[RESPONSE] Fetched {len(categories)} categories")
                        agent_logger.debug(
                            f"[RESPONSE] Fetched categories for {entities['chapter_code']}: {[{'code': cat.code, 'name': cat.name} for cat in categories]}")
                    if not categories:
                        messages.append({
                            "text": f"Ошибка: нет категорий для раздела {entities['chapter_code']}.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        continue
                    buttons = [
                        {"text": cat.name, "callback_data": f"CS:category_code={cat.code}"}
                        for cat in categories if cat.name
                    ]
                elif clarification_field == "subcategory_code" and entities.get("chapter_code") and entities.get(
                        "category_code"):
                    cat_key = f"{entities['chapter_code']}/{entities['category_code']}"
                    subcategories = subcategory_cache.get(cat_key)
                    if not subcategories:
                        subcategories = await api_client.get_subcategories(entities["chapter_code"],
                                                                           entities["category_code"])
                        subcategory_cache[cat_key] = subcategories
                        agent_logger.info(f"[RESPONSE] Fetched {len(subcategories)} subcategories")
                        agent_logger.debug(
                            f"[RESPONSE] Fetched subcategories for {cat_key}: {[{'code': sub.code, 'name': sub.name} for sub in subcategories]}")
                    if not subcategories:
                        messages.append({
                            "text": f"Ошибка: нет подкатегорий для категории {entities['category_code']}.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        continue
                    buttons = [
                        {"text": sub.name, "callback_data": f"CS:subcategory_code={sub.code}"}
                        for sub in subcategories if sub.name
                    ]

                if buttons:
                    keyboard = {
                        "inline_keyboard": [buttons[i:i + 3] for i in range(0, len(buttons), 3)] +
                                           [[{"text": "Отмена", "callback_data": "cancel"}]]
                    }
                    field_text = {
                        "chapter_code": "раздел",
                        "category_code": "категорию",
                        "subcategory_code": "подкатегорию"
                    }.get(clarification_field, "поле")
                    messages.append({
                        "text": f"Уточните {field_text} для расхода на сумму {entities['amount']} рублей:",
                        "keyboard": keyboard,
                        "request_indices": [action["request_index"]]
                    })
                else:
                    messages.append({
                        "text": f"Ошибка: нет доступных вариантов для поля {clarification_field}.",
                        "keyboard": None,
                        "request_indices": [action["request_index"]]
                    })

            state.output = {"messages": messages, "output": output}
            agent_logger.info("[RESPONSE] Response generated")
            agent_logger.debug(
                f"[RESPONSE] Response generated: {json.dumps(state.output, indent=2, ensure_ascii=False)}")
            return state
        except Exception as e:
            agent_logger.exception(f"[RESPONSE] Response agent error: {e}")
            state.output = {
                "messages": [{"text": "Ошибка при обработке. Попробуйте снова.", "request_indices": []}],
                "output": []
            }
            return state