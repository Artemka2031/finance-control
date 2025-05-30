"""
Response Agent: формирует финальные сообщения и клавиатуры для пользователя.
"""

import json
from typing import Dict, List

from ..utils import AgentState, agent_logger
from ...api_client import ApiClient
from ...utils.message_utils import format_operation_message
from .serialization import fetch_keyboard_items


async def response_agent(state: AgentState) -> AgentState:
    agent_logger.info("[RESPONSE] Entering response_agent")

    async with ApiClient(base_url=state.metadata.get("backend_url", "http://localhost:8000")) as api_client:
        messages: List[Dict] = []
        output: List[Dict] = []

        for action in state.actions:
            request_index = action["request_index"]
            request = next((r for r in state.requests if r["index"] == request_index), None)
            if not request:
                continue

            intent = request["intent"]
            entities = request["entities"]

            if action["needs_clarification"]:
                field = action["clarification_field"]
                if intent == "add_income":
                    text = f"Уточните категорию дохода (сумма {entities['amount']} рублей):"
                else:
                    text = f"Уточните {field} для операции (сумма {entities['amount']} рублей):"
                keyboard = {"inline_keyboard": []}

                items = await fetch_keyboard_items(api_client, field, request, request_index, state.metadata)
                if items:
                    keyboard["inline_keyboard"] = [[item] for item in items]
                    keyboard["inline_keyboard"].append(
                        [{"text": "Отмена", "callback_data": f"cancel:{request_index}"}]
                    )
                else:
                    text = f"Не удалось загрузить {field}. Попробуйте позже."
                    keyboard["inline_keyboard"] = [
                        [{"text": "Отмена", "callback_data": f"cancel:{request_index}"}]
                    ]

                messages.append({
                    "text": text,
                    "keyboard": keyboard,
                    "request_indices": [request_index],
                })

            elif action["ready_for_output"]:
                output.append({
                    "request_index": request_index,
                    "entities": entities,  # Ensure entities is a dict, not a string
                    "state": f"{intent.capitalize()}:confirm",
                })

        state.output = {
            "messages": messages,
            "output": output,
        }

        agent_logger.info("[RESPONSE] Response generated")
        agent_logger.debug(
            f"[RESPONSE] Response generated: {json.dumps(state.output, indent=2, ensure_ascii=False)}"
        )

    return state
