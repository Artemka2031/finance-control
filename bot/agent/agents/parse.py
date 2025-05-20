# Bot/agent/agents/parse.py
import json
from datetime import datetime
from typing import Dict

from ...api_client import ApiClient
from ..config import BACKEND_URL
from ..prompts import get_parse_prompt
from ..utils import AgentState, openai_client, agent_logger


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


async def validate_entities(entities: Dict, metadata: Dict) -> list[str]:
    """Validate entities against metadata and return missing or invalid fields."""
    missing = []
    chapter_code = entities.get("chapter_code")
    category_code = entities.get("category_code")
    subcategory_code = entities.get("subcategory_code")

    if not chapter_code or chapter_code not in metadata.get("expenses", {}):
        missing.append("chapter_code")
    elif category_code and category_code not in metadata.get("expenses", {}).get(chapter_code, {}).get("cats", {}):
        missing.append("category_code")
    elif subcategory_code and subcategory_code not in metadata.get("expenses", {}).get(chapter_code, {}).get("cats",
                                                                                                             {}).get(
            category_code, {}).get("subs", {}):
        missing.append("subcategory_code")
    elif not category_code:
        missing.append("category_code")
    elif not subcategory_code:
        missing.append("subcategory_code")

    if not entities.get("amount") or float(entities.get("amount", 0)) <= 0:
        missing.append("amount")
    if not entities.get("date"):
        missing.append("date")
    if not entities.get("wallet"):
        missing.append("wallet")

    return missing


async def parse_agent(state: AgentState) -> AgentState:
    """Parse user input to extract requests using LLM."""
    agent_logger.info("[PARSE] Entering parse_agent")

    if state.messages and state.messages[-1].get("content", "").startswith("Selected: CS:") and state.requests:
        agent_logger.info("[PARSE] Skipping parse due to selection, using existing requests")
        return state

    state.parse_iterations += 1
    if state.parse_iterations > 3:
        agent_logger.error("[PARSE] Max parse iterations exceeded")
        state.output = {
            "messages": [{"text": "Слишком много попыток обработки. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
        return state

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
            response_format={"type": "json_object"}
        )
        choice = response.choices[0].message
        agent_logger.info("[PARSE] Received OpenAI response")
        agent_logger.debug(
            f"[PARSE] OpenAI response: {json.dumps(json.loads(choice.model_dump_json()), indent=2, ensure_ascii=False)}")

        result = json.loads(choice.content)
        agent_logger.info("[PARSE] Parsed OpenAI result")
        agent_logger.debug(f"[PARSE] OpenAI parsed result: {json.dumps(result, indent=2, ensure_ascii=False)}")

        state.requests = []
        requests = result.get("requests", [])
        for i, req in enumerate(requests):
            if req.get("intent") != "add_expense":
                continue
            entities = req.get("entities", {})
            entities["input_text"] = input_text
            entities.setdefault("wallet", "project")
            entities.setdefault("coefficient", "1.0")
            entities.setdefault("date", datetime.now().strftime("%d.%m.%Y"))
            entities.setdefault("comment", "Расход")

            missing = await validate_entities(entities, state.metadata)
            state.requests.append({
                "intent": "add_expense",
                "entities": entities,
                "missing": missing
            })

        state.messages.append({"role": "assistant", "content": json.dumps(state.requests)})
        agent_logger.info(
            f"[PARSE] Parsed {len(state.requests)} requests: {json.dumps(state.requests, indent=2, ensure_ascii=False)}")

        if not state.requests:
            state.output = {
                "messages": [{"text": "Не удалось распознать запрос. Уточните, пожалуйста.", "request_indices": []}],
                "output": []
            }
    except Exception as e:
        agent_logger.exception(f"[PARSE] Parse agent error: {e}")
        state.output = {
            "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
    return state
