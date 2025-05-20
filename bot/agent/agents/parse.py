# Bot/agent/agents/parse.py
import json
from datetime import datetime, timedelta
from typing import Dict

from ...api_client import ApiClient
from ..config import BACKEND_URL
from ..prompts import get_parse_prompt
from ..utils import AgentState, openai_client, agent_logger, tools


async def fetch_metadata() -> Dict:
    """Fetch metadata from the backend."""
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            metadata = await api_client.get_metadata()
            agent_logger.info(f"[METADATA] Fetched metadata")
            agent_logger.debug(f"[METADATA] Fetched metadata: {json.dumps(metadata, ensure_ascii=False)}")
            return metadata
        except Exception as e:
            agent_logger.exception(f"[METADATA] Error fetching metadata: {e}")
            return {}


async def parse_agent(state: AgentState) -> AgentState:
    """Parse user input to extract requests."""
    agent_logger.info("[PARSE] Entering parse_agent")

    # Skip parsing if there is a selection and requests exist
    last_message = state.messages[-1] if state.messages else {}
    if last_message.get("content", "").startswith("Selected: CS:") and state.requests:
        agent_logger.info("[PARSE] Skipping parse due to selection, using existing requests")
        return state

    # Increment parse_iterations only during actual parsing
    state.parse_iterations += 1
    if state.parse_iterations > 3:
        agent_logger.error("[PARSE] Max parse iterations exceeded")
        state.output = {
            "messages": [{"text": "Слишком много попыток обработки. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
        return state

    # Fetch metadata if not already present
    if not state.metadata:
        state.metadata = await fetch_metadata()
        if not state.metadata:
            agent_logger.error("[PARSE] No metadata available")
            state.output = {
                "messages": [{"text": "Не удалось получить метаданные. Попробуйте снова.", "request_indices": []}],
                "output": []
            }
            return state

    input_text = state.messages[0]["content"] if state.messages else ""
    prompt = get_parse_prompt(input_text, state.metadata)
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            tools=[{"type": "function", "function": tool} for tool in tools]
        )
        choice = response.choices[0].message
        agent_logger.info("[PARSE] Received OpenAI response")
        agent_logger.debug(
            f"[PARSE] OpenAI response: {json.dumps(json.loads(choice.model_dump_json()), indent=2, ensure_ascii=False)}")

        if choice.tool_calls:
            agent_logger.info(f"[PARSE] Tool calls generated: {len(choice.tool_calls)}")
            state.messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "function": {
                            "name": call.function.name,
                            "arguments": json.loads(call.function.arguments)
                        }
                    } for call in choice.tool_calls
                ]
            })
            if not state.requests:
                state.requests = [{
                    "intent": "add_expense",
                    "entities": {
                        "input_text": input_text,
                        "chapter_code": "Р4",
                        "amount": "3000.0",
                        "date": (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y"),
                        "wallet": "project",
                        "coefficient": "1.0"
                    },
                    "missing": ["category_code", "subcategory_code"]
                }]
        else:
            result = json.loads(choice.content)
            agent_logger.info("[PARSE] Parsed OpenAI result")
            agent_logger.debug(f"[PARSE] OpenAI parsed result: {json.dumps(result, indent=2, ensure_ascii=False)}")
            requests = result.get("requests", [])
            state.requests = [
                {
                    "intent": req.get("intent", "add_expense"),
                    "entities": {
                        k: str(v) if isinstance(v, (int, float)) else v
                        for k, v in req.get("entities", {}).items()
                    },
                    "missing": req.get("missing", [])
                }
                for req in requests
            ]
            state.messages.append({"role": "assistant", "content": json.dumps(state.requests)})
            agent_logger.info(
                f"[PARSE] Parsed {len(state.requests)} requests: {json.dumps(state.requests, indent=2, ensure_ascii=False)}")
            if not state.requests:
                state.output = {
                    "messages": [
                        {"text": "Не удалось распознать запрос. Уточните, пожалуйста.", "request_indices": []}],
                    "output": []
                }
    except Exception as e:
        agent_logger.exception(f"[PARSE] Parse agent error: {e}")
        state.output = {
            "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
    return state