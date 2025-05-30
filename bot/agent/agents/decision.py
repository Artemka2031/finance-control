# bot/agent/agents/decision.py
import json

from ..prompts import DECISION_PROMPT
from ..utils import AgentState, openai_client, agent_logger


async def decision_agent(state: AgentState) -> AgentState:
    agent_logger.info("[DECISION] Entering decision_agent")
    actions = []
    combine_responses = True
    metadata = state.metadata or {}

    for idx, request in enumerate(state.requests):
        missing = request.get("missing", [])
        intent = request["intent"]
        entities = request["entities"]

        # Проверяем валидность chapter_code и category_code
        if intent in ["add_expense", "borrow"]:
            chapter_code = entities.get("chapter_code")
            category_code = entities.get("category_code")
            if chapter_code and chapter_code not in metadata.get("expenses", {}):
                missing.append("chapter_code")
            if chapter_code and category_code and category_code not in metadata.get("expenses", {}).get(chapter_code,
                                                                                                        {}).get("cats",
                                                                                                                {}):
                missing.append("category_code")

        needs_clarification = bool(missing)
        clarification_field = missing[0] if missing else None
        ready_for_output = not missing

        if needs_clarification:
            combine_responses = False

        actions.append({
            "request_index": idx,
            "needs_clarification": needs_clarification,
            "clarification_field": clarification_field,
            "ready_for_output": ready_for_output
        })

    state.actions = actions
    state.combine_responses = combine_responses
    agent_logger.info(f"[DECISION] Generated {len(actions)} actions: {actions}, combine: {combine_responses}")

    response = {
        "actions": actions,
        "combine_responses": combine_responses
    }
    state.messages.append({"role": "assistant", "content": json.dumps(response)})
    agent_logger.info("[DECISION] Received OpenAI response")
    agent_logger.debug(f"[DECISION] OpenAI response: {json.dumps(response, indent=2, ensure_ascii=False)}")

    return state
