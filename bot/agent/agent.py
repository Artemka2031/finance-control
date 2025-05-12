from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from openai import AsyncOpenAI
from datetime import datetime, timedelta
import json
from typing import List, Dict, Optional

from zstandard import backend

from ..api_client import ApiClient
from .config import OPENAI_API_KEY, BACKEND_URL
from .prompts import get_parse_prompt, DECISION_PROMPT, METADATA_PROMPT, RESPONSE_PROMPT
from .utils import fuzzy_match, configure_logger

key = "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"
Backend_url="http://localhost:8000/v1"

# Initialize clients
openai_client = AsyncOpenAI(api_key=key)
api_client = ApiClient(base_url=Backend_url)

# Logger
logger = configure_logger("[AGENT]", "blue")

# Cache for API responses
section_cache: List[Dict] = []
category_cache: Dict[str, List[Dict]] = {}
subcategory_cache: Dict[str, List[Dict]] = {}
creditor_cache: List[Dict] = []


# Model for agent state
class AgentState(BaseModel):
    input_text: str
    requests: List[Dict] = []
    actions: List[Dict] = []
    combine_responses: bool = False
    output: Dict = {"messages": [], "output": []}


async def parse_agent(state: AgentState) -> AgentState:
    """Parse user input to extract requests."""
    prompt = get_parse_prompt(state.input_text)
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        state.requests = result.get("requests", [])
        logger.debug(f"Parsed requests: {state.requests}")
    except Exception as e:
        logger.error(f"Error parsing input: {e}")
        state.output = {
            "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
            "output": []}
    return state


async def decision_agent(state: AgentState) -> AgentState:
    """Decide if clarification is needed and whether to combine responses."""
    if not state.requests:
        return state
    prompt = DECISION_PROMPT + f"\n\n**Входные данные**:\n{json.dumps({'requests': state.requests}, ensure_ascii=False)}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        state.actions = result.get("actions", [])
        state.combine_responses = result.get("combine_responses", False)
        logger.debug(f"Decision actions: {state.actions}, combine: {state.combine_responses}")
    except Exception as e:
        logger.error(f"Error in decision agent: {e}")
        state.output = {"messages": [{"text": "Ошибка при обработке. Попробуйте снова.", "request_indices": []}],
                        "output": []}
    return state


async def metadata_agent(state: AgentState) -> AgentState:
    """Validate entities against API."""
    global section_cache, category_cache, subcategory_cache, creditor_cache
    for i, action in enumerate(state.actions):
        if not action.get("needs_clarification"):
            continue
        request = state.requests[action["request_index"]]
        entities = request["entities"]
        missing = request["missing"]

        try:
            # Cache sections
            if not section_cache:
                section_cache = await api_client.get_sections()
            section_names = [sec.name for sec in section_cache]
            section_codes = {sec.name: sec.code for sec in section_cache}

            # Validate chapter_code
            if "chapter_code" in missing or entities.get("chapter_code"):
                if entities.get("chapter_code"):
                    match, score = fuzzy_match(entities["chapter_code"], section_names)
                    if score > 0:
                        entities["chapter_code"] = section_codes[match]
                        if "chapter_code" in missing:
                            missing.remove("chapter_code")
                    else:
                        missing.append("chapter_code")
                        entities["chapter_code"] = None

            # Validate category_code
            if ("category_code" in missing or entities.get("category_code")) and entities.get("chapter_code"):
                if entities["chapter_code"] not in category_cache:
                    category_cache[entities["chapter_code"]] = await api_client.get_categories(entities["chapter_code"])
                categories = category_cache[entities["chapter_code"]]
                category_names = [cat.name for cat in categories]
                category_codes = {cat.name: cat.code for cat in categories}
                if entities.get("category_code"):
                    match, score = fuzzy_match(entities["category_code"], category_names)
                    if score > 0:
                        entities["category_code"] = category_codes[match]
                        if "category_code" in missing:
                            missing.remove("category_code")
                    else:
                        missing.append("category_code")
                        entities["category_code"] = None

            # Validate subcategory_code
            if ("subcategory_code" in missing or entities.get("subcategory_code")) and entities.get(
                    "chapter_code") and entities.get("category_code"):
                cat_key = f"{entities['chapter_code']}/{entities['category_code']}"
                if cat_key not in subcategory_cache:
                    subcategory_cache[cat_key] = await api_client.get_subcategories(entities["chapter_code"],
                                                                                    entities["category_code"])
                subcategories = subcategory_cache[cat_key]
                subcategory_names = [sub.name for sub in subcategories]
                if entities.get("subcategory_code"):
                    match, score = fuzzy_match(entities["subcategory_code"], subcategory_names)
                    if score > 0:
                        entities["subcategory_code"] = next(sub.code for sub in subcategories if sub.name == match)
                        if "subcategory_code" in missing:
                            missing.remove("subcategory_code")
                    else:
                        missing.append("subcategory_code")
                        entities["subcategory_code"] = None

            # Validate creditor
            if ("creditor" in missing or entities.get("creditor")) and entities.get("wallet") in ["borrow", "repay"]:
                if not creditor_cache:
                    creditor_cache = await api_client.get_creditors()
                creditor_names = [cred.name for cred in creditor_cache]
                creditor_codes = {cred.name: cred.code for cred in creditor_cache}
                if entities.get("creditor"):
                    match, score = fuzzy_match(entities["creditor"], creditor_names)
                    if score > 0:
                        entities["creditor"] = creditor_codes[match]
                        if "creditor" in missing:
                            missing.remove("creditor")
                    else:
                        missing.append("creditor")
                        entities["creditor"] = None

            # Validate date
            if not entities.get("date"):
                entities["date"] = datetime.now().strftime("%d.%m.%Y")
            else:
                try:
                    if entities["date"].lower() == "вчера":
                        entities["date"] = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
                    else:
                        datetime.strptime(entities["date"], "%d.%m.%Y")
                except ValueError:
                    missing.append("date")
                    entities["date"] = None

            # Set default wallet and coefficient
            if not entities.get("wallet"):
                entities["wallet"] = "project"
            if not entities.get("coefficient"):
                entities["coefficient"] = 1.0

            request["entities"] = entities
            request["missing"] = missing
            action["needs_clarification"] = bool(missing)
            action["ready_for_output"] = not bool(missing)
            state.requests[action["request_index"]] = request
            state.actions[i] = action
        except Exception as e:
            logger.error(f"Error validating entities: {e}")
            state.output = {
                "messages": [{"text": "Сервер временно недоступен. Попробуйте снова.", "request_indices": []}],
                "output": []}
            return state
    return state


async def response_agent(state: AgentState) -> AgentState:
    """Generate response messages or final output."""
    if not state.actions:
        return state
    prompt = RESPONSE_PROMPT + f"\n\n**Входные данные**:\n{json.dumps({'actions': state.actions, 'requests': state.requests, 'combine_responses': state.combine_responses}, ensure_ascii=False)}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        state.output = {"messages": result.get("messages", []), "output": result.get("output", [])}
        logger.debug(f"Response generated: {state.output}")
    except Exception as e:
        logger.error(f"Error in response agent: {e}")
        state.output = {
            "messages": [{"text": "Ошибка при формировании ответа. Попробуйте снова.", "request_indices": []}],
            "output": []}
    return state


# Create LangGraph
graph = StateGraph(AgentState)
graph.add_node("parse_agent", parse_agent)
graph.add_node("decision_agent", decision_agent)
graph.add_node("metadata_agent", metadata_agent)
graph.add_node("response_agent", response_agent)
graph.add_edge("parse_agent", "decision_agent")
graph.add_edge("decision_agent", "metadata_agent")
graph.add_edge("metadata_agent", "response_agent")
graph.add_edge("response_agent", END)
graph.set_entry_point("parse_agent")

agent = graph.compile()


async def run_agent(input_text: str) -> Dict:
    """Run the agent with the given input text."""
    state = AgentState(input_text=input_text)
    result = await agent.ainvoke(state)
    return result.output
