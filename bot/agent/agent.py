# Bot/agent/agent.py
import json
from typing import Dict, Optional

from langgraph.graph import StateGraph, END

from .agents import parse_agent, decision_agent, metadata_agent, tools_agent, response_agent
from .config import BACKEND_URL
from .utils import AgentState, agent_logger
from ..api_client import ApiClient, ExpenseIn
from ..utils.message_utils import format_operation_message


class Agent:
    """Unified agent class for processing user requests using langgraph."""

    def __init__(self):
        self.graph = self._setup_graph()
        self.api_client = ApiClient(base_url=BACKEND_URL)

    def _setup_graph(self) -> StateGraph:
        """Setup langgraph with all agent nodes and edges."""
        graph = StateGraph(AgentState)
        graph.add_node("parse_agent", parse_agent)
        graph.add_node("decision_agent", decision_agent)
        graph.add_node("metadata_agent", metadata_agent)
        graph.add_node("tools_agent", tools_agent)
        graph.add_node("response_agent", response_agent)
        graph.add_edge("__start__", "parse_agent")
        graph.add_edge("tools_agent", "decision_agent")
        graph.add_conditional_edges("parse_agent", self._should_continue, {
            "parse_agent": "parse_agent",
            "tools_agent": "tools_agent",
            "decision_agent": "decision_agent"
        })
        graph.add_edge("decision_agent", "metadata_agent")
        graph.add_edge("metadata_agent", "response_agent")
        graph.add_edge("response_agent", END)
        return graph.compile()

    def _should_continue(self, state: AgentState) -> str:
        """Determine next agent based on state."""
        agent_logger.info("[CONTROL] Evaluating state continuation")
        if state.parse_iterations >= 3 and not state.messages[-1].get("content", "").startswith("Selected: CS:"):
            agent_logger.warning("[CONTROL] Max parse iterations reached, proceeding to decision_agent")
            return "decision_agent"
        if state.requests:
            for request in state.requests:
                if request.get("missing"):
                    agent_logger.info("[CONTROL] Missing fields detected, proceeding to decision_agent")
                    return "decision_agent"
        if state.messages[-1].get("tool_calls"):
            agent_logger.info("[CONTROL] Tool calls detected, proceeding to tools_agent")
            return "tools_agent"
        agent_logger.info("[CONTROL] No missing fields or tool calls, proceeding to decision_agent")
        return "decision_agent"

    async def run(self, input_text: str, interactive: bool = False, selection: Optional[str] = None,
                  prev_state: Optional[Dict] = None) -> Dict:
        """Run the agent with the given input text."""
        agent_logger.info(
            f"[RUN] Running agent with input: {input_text}, interactive: {interactive}, selection: {selection}")
        if prev_state:
            state = AgentState(**prev_state)
        else:
            state = AgentState(
                messages=[{"role": "user", "content": input_text}],
                requests=[],
                actions=[],
                output={"messages": [], "output": []}
            )

        if selection:
            if selection.startswith("CS:"):
                key, value = selection.replace("CS:", "").split("=")
                for req in state.requests:
                    req["entities"][key] = value
                    if key in req["missing"]:
                        req["missing"].remove(key)
                    if key == "chapter_code" and "category_code" not in req["missing"]:
                        req["missing"].append("category_code")
                    if key == "category_code" and "subcategory_code" not in req["missing"]:
                        req["missing"].append("subcategory_code")
                state.messages.append({"role": "user", "content": f"Selected: {selection}"})
            elif selection == "cancel":
                state.output = {
                    "messages": [{"text": "Действие отменено.", "request_indices": []}],
                    "output": []
                }
                return state.output

        try:
            result = await self.graph.ainvoke(state.dict())
            agent_logger.info(f"[RUN] Agent result")
            agent_logger.debug(f"[RUN] Agent result: {json.dumps(result['output'], indent=2, ensure_ascii=False)}")
            if not isinstance(result, dict) or "output" not in result:
                agent_logger.error(f"[RUN] Invalid result format: {result}")
                return {
                    "messages": [{"text": "Ошибка обработки результата. Попробуйте снова.", "request_indices": []}],
                    "output": []
                }
            if interactive:
                state_copy = {
                    "messages": result["messages"],
                    "requests": result["requests"],
                    "actions": result["actions"],
                    "combine_responses": result["combine_responses"],
                    "parse_iterations": result["parse_iterations"],
                    "metadata": result["metadata"]
                }
                result["output"]["state"] = state_copy
            return result["output"]
        except Exception as e:
            agent_logger.exception(f"[RUN] Agent execution failed: {e}")
            return {
                "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
                "output": []
            }

    async def process_request(self, input_text: str, interactive: bool = False, selection: Optional[str] = None,
                              prev_state: Optional[Dict] = None) -> Dict:
        """Process user request and handle expense submission."""
        agent_logger.info(
            f"[PROCESS] Processing request: {input_text}, interactive: {interactive}, selection: {selection}")

        # Clear caches before processing
        from .utils import section_cache, category_cache, subcategory_cache
        section_cache.clear()
        category_cache.clear()
        subcategory_cache.clear()

        result = await self.run(input_text, interactive, selection, prev_state)
        agent_logger.info(f"[PROCESS] Agent result")
        agent_logger.debug(f"[PROCESS] Agent result: {json.dumps(result, indent=2, ensure_ascii=False)}")

        requests = result.get("requests", [])
        if not requests and not result.get("messages"):
            agent_logger.error("[PROCESS] No requests or messages in result")
            return {
                "messages": [{"text": "Ошибка: Нет запросов для обработки.", "request_indices": []}],
                "output": []
            }

        # Форматируем итоговый результат для лога
        formatted_result = []
        for output in result.get("output", []):
            formatted_message = await format_operation_message(output.get("entities", {}), self.api_client)
            formatted_result.append(formatted_message)
        formatted_result_str = "\n".join(formatted_result) if formatted_result else "Нет операций для форматирования"

        agent_logger.info(
            f"[PROCESS] Operation summary:\n"
            f"User request: {input_text}\n"
            f"Response:\n{formatted_result_str}"
        )

        if result.get("messages"):
            return result

        request = requests[0]
        if not request.get("missing") and result.get("output"):
            expense = ExpenseIn(
                date=request["entities"]["date"],
                sec_code=request["entities"]["chapter_code"],
                cat_code=request["entities"]["category_code"],
                sub_code=request["entities"]["subcategory_code"],
                amount=float(request["entities"]["amount"]),
                comment=request["entities"].get("comment", "")
            )
            response = await self.api_client.add_expense(expense)
            if response.ok:
                agent_logger.info(f"[PROCESS] Expense added, task_id: {response.task_id}")
                formatted_message = await format_operation_message(request["entities"], self.api_client)
                return {
                    "messages": [{
                        "text": f"{formatted_message}\n\nПодтвердите операцию:",
                        "keyboard": None,
                        "request_indices": [0]
                    }],
                    "output": [{
                        "request_index": 0,
                        "entities": request["entities"],
                        "state": "Expense:confirm",
                        "task_id": response.task_id
                    }],
                    "state": result.get("state")
                }
            else:
                agent_logger.error(f"[PROCESS] Failed to add expense: {response.detail}")
                return {
                    "messages": [{"text": f"Ошибка при добавлении расхода: {response.detail}", "request_indices": []}],
                    "output": []
                }

        return result
