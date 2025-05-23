# Bot/agent/agent.py
import asyncio
import json
from typing import Dict, Optional, Any

from aiogram import Bot
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph import StateGraph, END

from .agents import parse_agent, decision_agent, metadata_agent, response_agent
from .config import BACKEND_URL
from .utils import AgentState, agent_logger
from ..api_client import ApiClient
from ..utils.message_utils import format_operation_message


class AnimationCallbackHandler(BaseCallbackHandler):
    """Callback handler for animating agent stages in Telegram."""

    def __init__(self, bot: Optional[Bot], chat_id: Optional[int], message_id: Optional[int]):
        super().__init__()
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.current_text = None

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        if not self.bot or not self.chat_id or not self.message_id:
            return
        await self._update_message("🔄 Начинаем обработку...")

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        if not self.bot or not self.chat_id or not self.message_id:
            return
        await self._update_message("✅ Обработка завершена")

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        stage_messages = {
            "parse_agent": "🔍 Разбираем ваш запрос...",
            "decision_agent": "🧠 Принимаем решение...",
            "metadata_agent": "📋 Собираем метаданные...",
            "response_agent": "📬 Формируем ответ..."
        }
        node_name = serialized.get("name", "")
        text = stage_messages.get(node_name, "🔄 Обрабатываем...")
        await self._update_message(text)

    async def _update_message(self, text: str) -> None:
        if self.current_text == text:
            return
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="HTML"
            )
            self.current_text = text
            await asyncio.sleep(0.3)  # Reduced delay for smoother animation
        except Exception as e:
            agent_logger.warning(f"Не удалось обновить анимацию: {e}")

class Agent:
    """Unified agent class for processing user requests using langgraph."""

    def __init__(self, bot: Optional[Bot] = None, chat_id: Optional[int] = None, message_id: Optional[int] = None):
        self.graph = self._setup_graph()
        self.api_client = ApiClient(base_url=BACKEND_URL)
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.callback_handler = AnimationCallbackHandler(bot, chat_id, message_id)

    def _setup_graph(self) -> StateGraph:
        """Setup langgraph with all agent nodes and edges."""
        graph = StateGraph(AgentState)
        graph.add_node("parse_agent", parse_agent)
        graph.add_node("decision_agent", decision_agent)
        graph.add_node("metadata_agent", metadata_agent)
        graph.add_node("response_agent", response_agent)
        graph.add_edge("__start__", "parse_agent")
        graph.add_conditional_edges("parse_agent", self._should_continue, {
            "parse_agent": "parse_agent",
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
        agent_logger.info("[CONTROL] No missing fields, proceeding to decision_agent")
        return "decision_agent"

    async def run(self, input_text: str, interactive: bool = False, selection: Optional[str] = None,
                  prev_state: Optional[Dict] = None) -> Dict:
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

        try:
            result = await self.graph.ainvoke(state.dict(), config={"callbacks": [self.callback_handler]})
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
        """Process user request and prepare output."""
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

        # Check if result is valid
        if not result.get("messages") and not result.get("output"):
            agent_logger.error("[PROCESS] No requests or messages in result")
            return {
                "messages": [{"text": "Ошибка: Нет запросов для обработки.", "request_indices": []}],
                "output": []
            }

        # Format result for logging
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

        return result