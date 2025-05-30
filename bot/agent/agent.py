"""
Основная «обёртка» над графом LangGraph.
Из старой версии убраны любые внутренние callback’и и вся логика анимации:
теперь анимация делается в Telegram-хендлерах.
"""

import json
from typing import Dict, Optional

from langgraph.graph import StateGraph, END

from .agents import parse_agent, decision_agent, metadata_agent, response_agent
from .agents.split import split_agent
from .config import BACKEND_URL
from .utils import AgentState, agent_logger
from ..api_client import ApiClient
from ..utils.message_utils import format_operation_message


class Agent:
    """Единая точка входа для всех LLM-агентов."""

    def __init__(self) -> None:
        self.graph = self._setup_graph()

    def _setup_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("split_agent", split_agent)
        graph.add_node("parse_agent", parse_agent)
        graph.add_node("decision_agent", decision_agent)
        graph.add_node("metadata_agent", metadata_agent)
        graph.add_node("response_agent", response_agent)
        graph.add_edge("__start__", "split_agent")
        graph.add_edge("split_agent", "parse_agent")
        graph.add_conditional_edges(
            "parse_agent",
            self._should_continue,
            {"parse_agent": "parse_agent", "decision_agent": "decision_agent"},
        )
        graph.add_edge("decision_agent", "metadata_agent")
        graph.add_edge("metadata_agent", "response_agent")
        graph.add_edge("response_agent", END)
        return graph.compile()

    @staticmethod
    def _should_continue(state: AgentState) -> str:
        if state.parse_iterations >= 3 and not state.messages[-1].get("content", "").startswith("Selected: CS:"):
            return "decision_agent"
        for req in state.requests:
            if req.get("missing"):
                return "decision_agent"
        return "decision_agent"

    async def run(
            self,
            input_text: str,
            interactive: bool = False,
            selection: Optional[str] = None,
            prev_state: Optional[Dict] = None,
    ) -> Dict:
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            if prev_state:
                state = AgentState(**prev_state)
            else:
                state = AgentState(messages=[{"role": "user", "content": input_text}])

            if selection:
                if selection.startswith("CS:"):
                    field, value = selection[3:].split("=", 1)
                    for req in state.requests:
                        req["entities"][field] = value
                        req["missing"] = [m for m in req["missing"] if m != field]
                elif selection.startswith("cancel"):
                    return {"messages": [], "output": []}

            try:
                result = await self.graph.ainvoke(state.dict())
            except Exception as e:
                agent_logger.exception("[RUN] Graph failed")
                return {
                    "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
                    "output": []
                }

            if interactive:
                result["output"]["state"] = {k: result[k] for k in (
                    "messages", "requests", "actions", "combine_responses", "parse_iterations", "metadata"
                )}

            agent_logger.debug(
                f"[RUN] Result output: {json.dumps(result.get('output', []), indent=2, ensure_ascii=False)}")
            for out in result.get("output", []):
                if not isinstance(out.get("entities"), dict):
                    agent_logger.error(
                        f"[RUN] Invalid entities type for output: {type(out.get('entities'))}, value: {out.get('entities')}")
                    continue
                msg = await format_operation_message(out["entities"], api_client)
                agent_logger.info(f"[SUMMARY]\n{msg}")

            return result["output"]

    async def process_request(
            self,
            input_text: str,
            interactive: bool = False,
            selection: Optional[str] = None,
            prev_state: Optional[Dict] = None,
    ) -> Dict:
        from .utils import section_cache, category_cache, subcategory_cache
        section_cache.clear()
        category_cache.clear()
        subcategory_cache.clear()
        return await self.run(input_text, interactive, selection, prev_state)
