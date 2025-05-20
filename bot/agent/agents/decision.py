# Bot/agent/agents/decision.py
import json

from ..prompts import DECISION_PROMPT
from ..utils import AgentState, openai_client, agent_logger


async def decision_agent(state: AgentState) -> AgentState:
    """Decide if clarification is needed and whether to combine responses."""
    agent_logger.info("[DECISION] Entering decision_agent")
    if not state.requests:
        agent_logger.info("[DECISION] No requests to process")
        return state
    prompt = DECISION_PROMPT + f"\n\n**Входные данные**:\n{json.dumps({'requests': state.requests}, ensure_ascii=False)}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        agent_logger.info("[DECISION] Received OpenAI response")
        agent_logger.debug(f"[DECISION] OpenAI response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        state.actions = []
        for i, req in enumerate(state.requests):
            action = result.get("actions", [{}])[i] if i < len(result.get("actions", [])) else {}
            state.actions.append({
                "request_index": i,
                "needs_clarification": action.get("needs_clarification", bool(req.get("missing", []))),
                "clarification_field": action.get("clarification_field",
                                                  req.get("missing", [None])[0] if req.get("missing") else None),
                "ready_for_output": action.get("ready_for_output", not bool(req.get("missing", [])))
            })
        state.combine_responses = result.get("combine_responses", False)
        state.messages.append({"role": "assistant", "content": json.dumps(state.actions)})
        agent_logger.info(
            f"[DECISION] Generated {len(state.actions)} actions: {json.dumps(state.actions, indent=2, ensure_ascii=False)}, combine: {state.combine_responses}")
    except Exception as e:
        agent_logger.exception(f"[DECISION] Decision agent error: {e}")
        state.output = {
            "messages": [{"text": "Ошибка при обработке. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
    return state
