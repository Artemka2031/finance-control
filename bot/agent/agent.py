# bot/agent/agent.py
# -*- coding: utf-8 -*-

# ------------------------------------------------------------------ #
# 0. Импорты                                                         #
# ------------------------------------------------------------------ #
import json
from typing import Dict, Optional

from langgraph.graph import StateGraph, END

from agent.agents import parse_agent, decision_agent, response_agent, metadata_agent
from agent.agents.split import split_agent
from agent.utils import AgentState, agent_logger

from api_client import ApiClient

from config import BACKEND_URL
from utils.message_utils import format_operation_message


# ------------------------------------------------------------------ #
# 1. Класс Agent                                                     #
# ------------------------------------------------------------------ #
class Agent:
    """Единая точка входа для всех LLM-агентов."""

    # -------------------------------------------------------------- #
    # 1.1 Инициализация                                              #
    # -------------------------------------------------------------- #
    def __init__(self) -> None:
        self.graph = self._setup_graph()

    # -------------------------------------------------------------- #
    # 1.2 Построение графа                                            #
    # -------------------------------------------------------------- #
    def _setup_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)

        # Узлы
        graph.add_node("split_agent", split_agent)
        graph.add_node("parse_agent", parse_agent)
        graph.add_node("decision_agent", decision_agent)
        graph.add_node("metadata_agent", metadata_agent)
        graph.add_node("response_agent", response_agent)

        # Рёбра
        graph.add_edge("__start__", "split_agent")
        graph.add_edge("split_agent", "parse_agent")
        graph.add_conditional_edges(
            "parse_agent",
            self._should_continue,
            {
                "parse_agent": "parse_agent",
                "decision_agent": "decision_agent",
            },
        )
        graph.add_edge("decision_agent", "metadata_agent")
        graph.add_edge("metadata_agent", "response_agent")
        graph.add_edge("response_agent", END)

        return graph.compile()

    # -------------------------------------------------------------- #
    # 1.3 Логика остановки парсинга                                   #
    # -------------------------------------------------------------- #
    @staticmethod
    def _should_continue(state: AgentState) -> str:
        # если разбор зашёл в тупик — переходим к decision_agent
        if state.parse_iterations >= 3 and not state.messages[-1].get("content", "").startswith("Selected: CS:"):
            return "decision_agent"
        # если остались «дырки» — тоже туда же
        for req in state.requests:
            if req.get("missing"):
                return "decision_agent"
        return "decision_agent"

    # -------------------------------------------------------------- #
    # 1.4 Основной запуск графа                                       #
    # -------------------------------------------------------------- #
    async def run(
            self,
            input_text: str,
            interactive: bool = False,
            selection: Optional[str] = None,
            prev_state: Optional[Dict] = None,
    ) -> Dict:
        """Запуск графа LangGraph и пост-обработка результата."""
        async with ApiClient(base_url=BACKEND_URL) as api_client:
            # -------- 2. Подготовка начального состояния ------------
            if prev_state:
                state = AgentState(**prev_state)
            else:
                state = AgentState(messages=[{"role": "user", "content": input_text}])

            # -------- 3. Обработка inline-selection -----------------
            if selection:
                if selection.startswith("CS:"):
                    field, value = selection[3:].split("=", 1)
                    for req in state.requests:
                        req["entities"][field] = value
                        req["missing"] = [m for m in req["missing"] if m != field]
                elif selection.startswith("cancel"):
                    return {"messages": [], "output": []}

            # -------- 4. Запуск графа --------------------------------
            try:
                result = await self.graph.ainvoke(state.dict())
            except Exception:
                agent_logger.exception("[RUN] Graph failed")
                return {
                    "messages": [
                        {"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}
                    ],
                    "output": [],
                }

            # -------- 5. Формирование output-словаря -----------------
            output_dict = result.get("output", {})  # всегда dict из response_agent

            # При interactive добавляем полный state внутрь output_dict
            if interactive:
                output_dict["state"] = {
                    k: result[k]
                    for k in (
                        "messages",
                        "requests",
                        "actions",
                        "combine_responses",
                        "parse_iterations",
                        "metadata",
                    )
                }

            # -------- 6. Логирование JSON-выгрузки -------------------
            agent_logger.debug(
                f"[RUN] Result output: {json.dumps(output_dict, indent=2, ensure_ascii=False)}"
            )

            # -------- 7. Резюме для каждой операции -----------------
            for out in output_dict.get("output", []):
                if not isinstance(out.get("entities"), dict):
                    agent_logger.error(
                        f"[RUN] Invalid entities type for output: {type(out.get('entities'))}, "
                        f"value: {out.get('entities')}"
                    )
                    continue
                msg = await format_operation_message(out["entities"], api_client)
                agent_logger.info(f"[SUMMARY]\n{msg}")

            # -------- 8. Возврат только output-словаря --------------
            return output_dict

    # -------------------------------------------------------------- #
    # 1.5 Публичный метод-обёртка                                     #
    # -------------------------------------------------------------- #
    async def process_request(
            self,
            input_text: str,
            interactive: bool = False,
            selection: Optional[str] = None,
            prev_state: Optional[Dict] = None,
    ) -> Dict:
        """
        Сбрасывает кэш метаданных и вызывает `run()`.
        """
        from .utils import section_cache, category_cache, subcategory_cache

        section_cache.clear()
        category_cache.clear()
        subcategory_cache.clear()

        return await self.run(input_text, interactive, selection, prev_state)
