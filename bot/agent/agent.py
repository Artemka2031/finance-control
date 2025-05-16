import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from .config import OPENAI_API_KEY, BACKEND_URL
from .prompts import get_parse_prompt, DECISION_PROMPT, RESPONSE_PROMPT
from .utils import fuzzy_match
from ..api_client import ApiClient, CodeName
from ..utils.logging import configure_logger

# Logger
logger = configure_logger("[AGENT]", "blue")

# Initialize OpenAI client
logger.debug(f"Initializing OpenAI client with API key: {'*' * len(OPENAI_API_KEY[:-4]) + OPENAI_API_KEY[-4:]}")
try:
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise

# Cache for API responses
section_cache: List[CodeName] = []
category_cache: Dict[str, List[CodeName]] = {}
subcategory_cache: Dict[str, List[CodeName]] = {}
creditor_cache: List[CodeName] = []

async def validate_category(category_name: str, chapter_code: str) -> Dict[str, Any]:
    """Validate category name against API and return category code."""
    logger.info(f"[VALIDATE] Validating category: {category_name}, chapter: {chapter_code}")
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            categories = category_cache.get(chapter_code)
            if not categories:
                logger.debug(f"[VALIDATE] Fetching categories for chapter_code: {chapter_code}")
                categories = await api_client.get_categories(chapter_code)
                if not categories:
                    logger.error(f"[VALIDATE] No categories found for chapter_code: {chapter_code}")
                    return {"category_code": None, "success": False, "error": "No categories available"}
                category_cache[chapter_code] = categories
            category_names = [cat.name for cat in categories]
            match, score = fuzzy_match(category_name, category_names)
            if score > 0.9:
                result = {"category_code": next(cat.code for cat in categories if cat.name == match), "success": True}
                logger.info(f"[VALIDATE] Validation result: {result}")
                return result
            result = {"category_code": None, "success": False}
            logger.info(f"[VALIDATE] Validation result: {result}")
            return result
        except Exception as e:
            logger.exception(f"[VALIDATE] Error in validate_category: {e}")
            return {"category_code": None, "success": False, "error": str(e)}

# Определяем инструменты
tools = [
    {
        "name": "validate_category",
        "description": "Validate a category name against the API for a given chapter code.",
        "parameters": {
            "type": "object",
            "properties": {
                "category_name": {"type": "string", "description": "Name of the category to validate"},
                "chapter_code": {"type": "string", "description": "Chapter code (e.g., P4)"}
            },
            "required": ["category_name", "chapter_code"]
        }
    }
]

class Request(TypedDict):
    intent: str
    entities: Dict[str, Optional[str]]
    missing: List[str]

class Action(TypedDict):
    request_index: int
    needs_clarification: bool
    clarification_field: Optional[str]
    ready_for_output: bool

class AgentState(BaseModel):
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    requests: List[Request] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    combine_responses: bool = False
    output: Dict = Field(default_factory=lambda: {"messages": [], "output": []})
    parse_iterations: int = Field(default=0)
    metadata: Optional[Dict] = Field(default=None)

async def fetch_metadata() -> Dict:
    """Запрашивает метаданные с бэкенда."""
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            metadata = await api_client.get_metadata()
            logger.info(f"[METADATA] Fetched metadata: {json.dumps(metadata, ensure_ascii=False)}")
            return metadata
        except Exception as e:
            logger.exception(f"[METADATA] Error fetching metadata: {e}")
            return {}

async def parse_agent(state: AgentState) -> AgentState:
    """Parse user input to extract requests."""
    logger.info("[PARSE] Entering parse_agent")

    # Пропускаем парсинг, если есть selection и requests уже существуют
    last_message = state.messages[-1] if state.messages else {}
    if last_message.get("content", "").startswith("Selected: CS:") and state.requests:
        logger.info("[PARSE] Skipping parse due to selection, using existing requests")
        return state

    # Увеличиваем parse_iterations только при реальном парсинге
    state.parse_iterations += 1
    if state.parse_iterations > 3:
        logger.error("[PARSE] Max parse iterations exceeded")
        state.output = {
            "messages": [{"text": "Слишком много попыток обработки. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
        return state

    # Запрашиваем метаданные, если они ещё не получены
    if not state.metadata:
        state.metadata = await fetch_metadata()
        if not state.metadata:
            logger.error("[PARSE] No metadata available")
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
        logger.debug(
            f"[PARSE] OpenAI response: {json.dumps(json.loads(choice.model_dump_json()), indent=2, ensure_ascii=False)}")

        if choice.tool_calls:
            logger.info(f"[PARSE] Tool calls generated: {len(choice.tool_calls)}")
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
            logger.info(f"[PARSE] OpenAI parsed result: {json.dumps(result, indent=2, ensure_ascii=False)}")
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
            logger.info(
                f"[PARSE] Parsed {len(state.requests)} requests: {json.dumps(state.requests, indent=2, ensure_ascii=False)}")
            if not state.requests:
                state.output = {
                    "messages": [
                        {"text": "Не удалось распознать запрос. Уточните, пожалуйста.", "request_indices": []}],
                    "output": []
                }
    except Exception as e:
        logger.exception(f"[PARSE] Parse agent error: {e}")
        state.output = {
            "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
    return state

async def decision_agent(state: AgentState) -> AgentState:
    """Decide if clarification is needed and whether to combine responses."""
    logger = configure_logger("[DECISION]", "yellow")
    logger.info("[DECISION] Entering decision_agent")
    if not state.requests:
        logger.info("[DECISION] No requests to process")
        return state
    prompt = DECISION_PROMPT + f"\n\n**Входные данные**:\n{json.dumps({'requests': state.requests}, ensure_ascii=False)}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        logger.info(f"[DECISION] OpenAI response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        state.actions = [
            {
                "request_index": action.get("request_index", 0),
                "needs_clarification": action.get("needs_clarification", False),
                "clarification_field": action.get("clarification_field"),
                "ready_for_output": action.get("ready_for_output", False)
            }
            for action in result.get("actions", [])
        ]
        state.combine_responses = result.get("combine_responses", False)
        state.messages.append({"role": "assistant", "content": json.dumps(state.actions)})
        logger.info(
            f"[DECISION] Generated {len(state.actions)} actions: {json.dumps(state.actions, indent=2, ensure_ascii=False)}, combine: {state.combine_responses}")
    except Exception as e:
        logger.exception(f"[DECISION] Decision agent error: {e}")
        state.output = {
            "messages": [{"text": "Ошибка при обработке. Попробуйте снова.", "request_indices": []}],
            "output": []
        }
    return state

async def metadata_agent(state: AgentState) -> AgentState:
    """Validate entities against API."""
    logger = configure_logger("[METADATA]", "magenta")
    logger.info("[METADATA] Entering metadata_agent")
    global section_cache, category_cache, subcategory_cache, creditor_cache
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
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
                        if not section_cache:
                            logger.error("[METADATA] API returned empty sections")
                            state.output = {
                                "messages": [
                                    {"text": "Сервер не вернул разделы. Попробуйте снова.", "request_indices": []}],
                                "output": []
                            }
                            return state
                        logger.info(
                            f"[METADATA] Fetched {len(section_cache)} sections: {[{'code': sec.code, 'name': sec.name} for sec in section_cache]}")
                    section_names = [sec.name for sec in section_cache]
                    section_codes = {sec.name: sec.code for sec in section_cache}

                    # Validate chapter_code
                    if "chapter_code" in missing or entities.get("chapter_code"):
                        if entities.get("chapter_code"):
                            if entities["chapter_code"] in [sec.code for sec in section_cache]:
                                if "chapter_code" in missing:
                                    missing.remove("chapter_code")
                            else:
                                missing.append("chapter_code")
                                entities["chapter_code"] = None

                    # Validate category_code
                    if ("category_code" in missing or entities.get("category_code")) and entities.get("chapter_code"):
                        if entities["chapter_code"] not in category_cache:
                            category_cache[entities["chapter_code"]] = await api_client.get_categories(
                                entities["chapter_code"])
                            if not category_cache[entities["chapter_code"]]:
                                logger.error(f"[METADATA] No categories for chapter_code: {entities['chapter_code']}")
                                state.output = {
                                    "messages": [
                                        {"text": f"Нет категорий для раздела {entities['chapter_code']}.",
                                         "request_indices": []}],
                                    "output": []
                                }
                                return state
                            logger.info(
                                f"[METADATA] Fetched {len(category_cache[entities['chapter_code']])} categories for {entities['chapter_code']}")
                        categories = category_cache[entities["chapter_code"]]
                        category_names = [cat.name for cat in categories]
                        category_codes = {cat.name: cat.code for cat in categories}
                        if entities.get("category_code"):
                            if entities["category_code"] in [cat.code for cat in categories]:
                                if "category_code" in missing:
                                    missing.remove("category_code")
                            else:
                                match, score = fuzzy_match(entities["category_code"], category_names)
                                if score > 0.9:
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
                            if not subcategory_cache[cat_key]:
                                logger.warning(f"[METADATA] No subcategories for {cat_key}")
                            logger.info(
                                f"[METADATA] Fetched {len(subcategory_cache[cat_key])} subcategories for {cat_key}")
                        subcategories = subcategory_cache[cat_key]
                        subcategory_names = [sub.name for sub in subcategories]
                        subcategory_codes = {sub.name: sub.code for sub in subcategories}
                        if entities.get("subcategory_code"):
                            if entities["subcategory_code"] in [sub.code for sub in subcategories]:
                                if "subcategory_code" in missing:
                                    missing.remove("subcategory_code")
                            else:
                                match, score = fuzzy_match(entities["subcategory_code"], subcategory_names)
                                if score > 0.9:
                                    entities["subcategory_code"] = subcategory_codes[match]
                                    if "subcategory_code" in missing:
                                        missing.remove("subcategory_code")
                                else:
                                    missing.append("subcategory_code")
                                    entities["subcategory_code"] = None

                    # Validate creditor
                    if ("creditor" in missing or entities.get("creditor")) and entities.get("wallet") in ["borrow",
                                                                                                          "repay"]:
                        if not creditor_cache:
                            creditor_cache = await api_client.get_creditors()
                            logger.info(f"[METADATA] Fetched {len(creditor_cache)} creditors")
                        creditor_names = [cred.name for cred in creditor_cache]
                        creditor_codes = {cred.name: cred.code for cred in creditor_cache}
                        if entities.get("creditor"):
                            match, score = fuzzy_match(entities["creditor"], creditor_names)
                            if score > 0.9:
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
                            if entities["date"].lower() == "позавчера":
                                entities["date"] = (datetime.now() - timedelta(days=2)).strftime("%d.%m.%Y")
                            elif entities["date"].lower() == "вчера":
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
                        entities["coefficient"] = "1.0"

                    request["entities"] = entities
                    request["missing"] = missing
                    action["needs_clarification"] = bool(missing)
                    action["ready_for_output"] = not bool(missing)
                    state.requests[action["request_index"]] = request
                    state.actions[i] = action
                    logger.info(
                        f"[METADATA] Validated request {action['request_index']}: entities={json.dumps(entities, ensure_ascii=False)}, missing={missing}")
                except Exception as e:
                    logger.exception(f"[METADATA] Error validating entities: {e}")
                    state.output = {
                        "messages": [{"text": "Сервер временно недоступен. Попробуйте снова.", "request_indices": []}],
                        "output": []
                    }
                    return state
        finally:
            state.messages.append({"role": "assistant", "content": json.dumps({"entities_validated": state.requests})})
            logger.info("[METADATA] Metadata agent completed")
    return state

async def tools_agent(state: AgentState) -> AgentState:
    """Handle tool calls."""
    logger = configure_logger("[TOOLS]", "green")
    logger.info("[TOOLS] Entering tools_agent")
    last_message = state.messages[-1]
    if last_message.get("tool_calls"):
        for tool_call in last_message["tool_calls"]:
            if tool_call["function"]["name"] == "validate_category":
                args = tool_call["function"]["arguments"]
                logger.info(f"[TOOLS] Calling validate_category: {args}")
                result = await validate_category(
                    category_name=args["category_name"],
                    chapter_code=args["chapter_code"]
                )
                state.messages.append({
                    "role": "tool",
                    "content": json.dumps(result),
                    "tool_call_id": tool_call["id"]
                })
                logger.info(f"[TOOLS] Validate_category result: {result}")
                if result["success"]:
                    for req in state.requests:
                        req["entities"]["category_code"] = result["category_code"]
                        if "category_code" in req["missing"]:
                            req["missing"].remove("category_code")
                        if "subcategory_code" not in req["missing"]:
                            req["missing"].append("subcategory_code")
                        logger.info(f"[TOOLS] Updated request: {json.dumps(req, ensure_ascii=False)}")
    return state

async def response_agent(state: AgentState) -> AgentState:
    """Generate response messages or final output."""
    logger = configure_logger("[RESPONSE]", "red")
    logger.info("[RESPONSE] Entering response_agent")
    global section_cache, category_cache, subcategory_cache
    if not state.actions:
        logger.info("[RESPONSE] No actions to process")
        return state

    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            messages = []
            output = []
            for action in state.actions:
                request = state.requests[action["request_index"]]
                entities = request["entities"]
                missing = request["missing"]

                if not action.get("needs_clarification"):
                    if action.get("ready_for_output"):
                        # Получаем имена категорий и подкатегорий для вывода
                        category_name = "Unknown"
                        subcategory_name = "Unknown"
                        if entities.get("chapter_code") and entities.get("category_code"):
                            categories = category_cache.get(entities["chapter_code"])
                            if not categories:
                                categories = await api_client.get_categories(entities["chapter_code"])
                                category_cache[entities["chapter_code"]] = categories
                            category_name = next(
                                (cat.name for cat in categories if cat.code == entities["category_code"]), "Unknown")
                        if entities.get("chapter_code") and entities.get("category_code") and entities.get(
                                "subcategory_code"):
                            cat_key = f"{entities['chapter_code']}/{entities['category_code']}"
                            subcategories = subcategory_cache.get(cat_key)
                            if not subcategories:
                                subcategories = await api_client.get_subcategories(entities["chapter_code"],
                                                                                   entities["category_code"])
                                subcategory_cache[cat_key] = subcategories
                            subcategory_name = next(
                                (sub.name for sub in subcategories if sub.code == entities["subcategory_code"]),
                                "Unknown")
                        messages.append({
                            "text": f"Расход {entities['amount']} на {category_name} ({subcategory_name}) записан.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        output.append({
                            "request_index": action["request_index"],
                            "entities": entities,
                            "state": "Expense:confirm"  # Для FSM
                        })
                        continue

                clarification_field = action["clarification_field"]
                buttons = []
                if clarification_field == "chapter_code":
                    if not section_cache:
                        section_cache = await api_client.get_sections()
                        logger.info(f"[RESPONSE] Fetched {len(section_cache)} sections")
                    if not section_cache:
                        messages.append({
                            "text": "Ошибка: нет доступных разделов.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        continue
                    buttons = [
                        {"text": sec.name, "callback_data": f"CS:chapter_code={sec.code}"}
                        for sec in section_cache if sec.name
                    ]
                elif clarification_field == "category_code" and entities.get("chapter_code"):
                    categories = category_cache.get(entities["chapter_code"])
                    if not categories:
                        categories = await api_client.get_categories(entities["chapter_code"])
                        category_cache[entities["chapter_code"]] = categories
                        logger.info(f"[RESPONSE] Fetched {len(categories)} categories for {entities['chapter_code']}")
                    if not categories:
                        messages.append({
                            "text": f"Ошибка: нет категорий для раздела {entities['chapter_code']}.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        continue
                    buttons = [
                        {"text": cat.name, "callback_data": f"CS:category_code={cat.code}"}
                        for cat in categories if cat.name
                    ]
                elif clarification_field == "subcategory_code" and entities.get("chapter_code") and entities.get(
                        "category_code"):
                    cat_key = f"{entities['chapter_code']}/{entities['category_code']}"
                    subcategories = subcategory_cache.get(cat_key)
                    if not subcategories:
                        subcategories = await api_client.get_subcategories(entities["chapter_code"],
                                                                           entities["category_code"])
                        subcategory_cache[cat_key] = subcategories
                        logger.info(f"[RESPONSE] Fetched {len(subcategories)} subcategories for {cat_key}")
                    if not subcategories:
                        messages.append({
                            "text": f"Ошибка: нет подкатегорий для категории {entities['category_code']}.",
                            "keyboard": None,
                            "request_indices": [action["request_index"]]
                        })
                        continue
                    buttons = [
                        {"text": sub.name, "callback_data": f"CS:subcategory_code={sub.code}"}
                        for sub in subcategories if sub.name
                    ]

                if buttons:
                    keyboard = {
                        "inline_keyboard": [buttons[i:i + 3] for i in range(0, len(buttons), 3)] +
                                           [[{"text": "Отмена", "callback_data": "cancel"}]]
                    }
                    field_text = {
                        "chapter_code": "раздел",
                        "category_code": "категорию",
                        "subcategory_code": "подкатегорию"
                    }.get(clarification_field, "поле")
                    messages.append({
                        "text": f"Уточните {field_text} для расхода на сумму {entities['amount']} рублей:",
                        "keyboard": keyboard,
                        "request_indices": [action["request_index"]]
                    })
                else:
                    messages.append({
                        "text": f"Ошибка: нет доступных вариантов для поля {clarification_field}.",
                        "keyboard": None,
                        "request_indices": [action["request_index"]]
                    })

            state.output = {"messages": messages, "output": output}
            logger.info(f"[RESPONSE] Response generated: {json.dumps(state.output, indent=2, ensure_ascii=False)}")
            return state
        except Exception as e:
            logger.exception(f"[RESPONSE] Response agent error: {e}")
            state.output = {
                "messages": [{"text": "Ошибка при обработке. Попробуйте снова.", "request_indices": []}],
                "output": []
            }
            return state

def should_continue(state: AgentState) -> str:
    logger = configure_logger("[CONTROL]", "magenta")
    if state.parse_iterations >= 3 and not state.messages[-1].get("content", "").startswith("Selected: CS:"):
        logger.warning("[CONTROL] Max parse iterations reached, proceeding to decision_agent")
        return "decision_agent"
    if state.requests:
        for request in state.requests:
            if request.get("missing"):
                logger.info("[CONTROL] Missing fields detected, proceeding to decision_agent")
                return "decision_agent"
    if state.messages[-1].get("tool_calls"):
        logger.info("[CONTROL] Tool calls detected, proceeding to tools_agent")
        return "tools_agent"
    logger.info("[CONTROL] No missing fields or tool calls, proceeding to decision_agent")
    return "decision_agent"

# Создаем граф
graph = StateGraph(AgentState)
graph.add_node("parse_agent", parse_agent)
graph.add_node("decision_agent", decision_agent)
graph.add_node("metadata_agent", metadata_agent)
graph.add_node("tools_agent", tools_agent)
graph.add_node("response_agent", response_agent)
graph.add_edge("__start__", "parse_agent")
graph.add_edge("tools_agent", "decision_agent")
graph.add_conditional_edges("parse_agent", should_continue, {
    "parse_agent": "parse_agent",
    "tools_agent": "tools_agent",
    "decision_agent": "decision_agent"
})
graph.add_edge("decision_agent", "metadata_agent")
graph.add_edge("metadata_agent", "response_agent")
graph.add_edge("response_agent", END)
agent = graph.compile()

async def run_agent(input_text: str, interactive: bool = False, selection: Optional[str] = None,
                    prev_state: Optional[Dict] = None) -> Dict:
    """Run the agent with the given input text."""
    logger.info(f"[RUN] Running agent with input: {input_text}, interactive: {interactive}, selection: {selection}")
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
        # Обработка выбора пользователя
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
        result = await agent.ainvoke(state.dict())
        logger.info(f"[RUN] Agent result: {json.dumps(result['output'], indent=2, ensure_ascii=False)}")
        if not isinstance(result, dict) or "output" not in result:
            logger.error(f"[RUN] Invalid result format: {result}")
            return {
                "messages": [{"text": "Ошибка обработки результата. Попробуйте снова.", "request_indices": []}],
                "output": []
            }
        if interactive:
            # Сохраняем копию состояния без циклических ссылок
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
        logger.exception(f"[RUN] Agent execution failed: {e}")
        return {
            "messages": [{"text": "Не удалось обработать запрос. Попробуйте снова.", "request_indices": []}],
            "output": []
        }