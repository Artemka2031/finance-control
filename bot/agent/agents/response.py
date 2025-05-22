import json
from ..utils import agent_logger, openai_client, AgentState
from ..prompts import RESPONSE_PROMPT


async def response_agent(state: AgentState) -> AgentState:
    """Generate response messages based on agent state."""
    agent_logger.info("[RESPONSE] Entering response_agent")
    if not state.actions:
        agent_logger.info("[RESPONSE] No actions to process")
        state.output = {
            "messages": [{"text": "Нет запросов для обработки.", "request_indices": []}],
            "output": []
        }
        return state

    prompt = RESPONSE_PROMPT + f"\n\n**Входные данные**:\n{json.dumps({'actions': state.actions, 'requests': state.requests}, ensure_ascii=False)}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Исправлено с gpt-4.1-mini
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        agent_logger.info("[RESPONSE] Response generated")
        agent_logger.debug(f"[RESPONSE] Response generated: {json.dumps(result, indent=2, ensure_ascii=False)}")

        # Modify callback_data to include request_index
        for message in result.get("messages", []):
            keyboard = message.get("keyboard")
            if keyboard:
                for row in keyboard["inline_keyboard"]:
                    for button in row:
                        if button["callback_data"].startswith("CS:"):
                            parts = button["callback_data"].split(":")
                            if len(parts) == 2:
                                field, value = parts[1].split("=")
                                request_index = message["request_indices"][0]
                                button["callback_data"] = f"CS:{field}={value}:{request_index}"
                            elif button["callback_data"] == "cancel":
                                request_index = message["request_indices"][0]
                                button["callback_data"] = f"cancel:{request_index}"

        state.output = {
            "messages": result.get("messages", []),
            "output": result.get("output", [])
        }
    except Exception as e:
        agent_logger.exception(f"[RESPONSE] Response agent error: {e}")
        state.output = {
            "messages": [{"text": "Ошибка при формировании ответа. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
    return state
