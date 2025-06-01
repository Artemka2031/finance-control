import json
import re
from datetime import datetime
from typing import Dict, List

from ..config import BACKEND_URL
from ..prompts import get_parse_prompt
from ..utils import AgentState, openai_client, agent_logger
from ...api_client import ApiClient

_LOAN_RE = re.compile(
    r"\b(в\s+долг|за\s+сч[её]т|занима[юе]|бер[уё]|(?:у|от)\s+[\w\-]+?\s+занял)\b",
    flags=re.IGNORECASE,
)


async def validate_entities(entities: Dict, api_client: ApiClient, intent: str) -> List[str]:
    """Return list of missing / invalid required fields."""
    agent_logger.info(f"[PARSE] Validating entities for intent: {intent}")
    missing: List[str] = []

    if intent == "add_income":
        if not entities.get("amount") or float(entities.get("amount", 0)) <= 0:
            missing.append("amount")
        if not entities.get("date"):
            missing.append("date")
        categories = await api_client.get_incomes()
        if (
                not entities.get("category_code")
                or entities["category_code"] not in {cat.code for cat in categories}
        ):
            missing.append("category_code")
        if not entities.get("comment"):
            missing.append("comment")

    elif intent in ["add_expense", "borrow"]:
        sections = await api_client.get_sections()
        if (
                not entities.get("chapter_code")
                or entities["chapter_code"] not in {sec.code for sec in sections}
        ):
            missing.append("chapter_code")
        elif entities.get("chapter_code"):
            categories = await api_client.get_categories(entities["chapter_code"])
            if (
                    not entities.get("category_code")
                    or entities["category_code"] not in {cat.code for cat in categories}
            ):
                missing.append("category_code")
            elif entities.get("category_code"):
                subcategories = await api_client.get_subcategories(
                    entities["chapter_code"], entities["category_code"]
                )
                if (
                        not entities.get("subcategory_code")
                        or entities["subcategory_code"] not in {sub.code for sub in subcategories}
                ):
                    missing.append("subcategory_code")
        if not entities.get("amount") or float(entities.get("amount", 0)) <= 0:
            missing.append("amount")
        if not entities.get("date"):
            missing.append("date")
        if not entities.get("wallet"):
            missing.append("wallet")
        if intent == "borrow":
            creditors = await api_client.get_creditors()
            if (
                    not entities.get("creditor")
                    or entities["creditor"] not in {cred.name for cred in creditors}
            ):
                missing.append("creditor")
            if (
                    not entities.get("coefficient")
                    or float(entities.get("coefficient", 1.0)) <= 0
            ):
                missing.append("coefficient")

    elif intent == "repay":
        creditors = await api_client.get_creditors()
        if (
                not entities.get("creditor")
                or entities["creditor"] not in {cred.name for cred in creditors}
        ):
            missing.append("creditor")
        if not entities.get("amount") or float(entities.get("amount", 0)) <= 0:
            missing.append("amount")
        if not entities.get("date"):
            missing.append("date")
        if not entities.get("wallet"):
            missing.append("wallet")

    agent_logger.debug(f"[PARSE] Missing fields: {missing}")
    return missing


async def parse_agent(state: AgentState) -> AgentState:
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        agent_logger.info("[PARSE] Entering parse_agent")

        # Если был выбор из клавиатуры
        if (
                state.messages
                and state.messages[-1].get("content", "").startswith("Selected: CS:")
                and state.requests
        ):
            agent_logger.info("[PARSE] Skipped due to selection")
            return state

        # Safety-ограничение
        state.parse_iterations += 1
        if state.parse_iterations > 3:
            agent_logger.error("[PARSE] Max iterations exceeded")
            state.output = {
                "messages": [
                    {
                        "text": "Слишком много попыток обработки. Попробуйте снова.",
                        "request_indices": [],
                    }
                ],
                "output": [],
            }
            return state

        # Загрузка метаданных
        if not state.metadata:
            try:
                state.metadata = await api_client.get_metadata()
                agent_logger.info("[PARSE] Metadata loaded successfully")
            except Exception as e:
                agent_logger.error(f"[PARSE] Failed to load metadata: {e}")
                state.output = {
                    "messages": [
                        {
                            "text": "Не удалось получить метаданные. Попробуйте снова.",
                            "request_indices": [],
                        }
                    ],
                    "output": [],
                }
                return state

        # Какие куски парсим
        parts: List[str] = state.parts or [
            state.messages[0]["content"] if state.messages else ""
        ]
        state.requests = []

        # Цикл по частям
        for part_idx, part_text in enumerate(parts):
            prompt = get_parse_prompt(part_text, state.metadata)

            try:
                resp = await openai_client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                choice = resp.choices[0].message
                agent_logger.info(f"[PARSE] LLM answered for part {part_idx}")
                agent_logger.debug(
                    f"[PARSE] Raw LLM part {part_idx}: "
                    f"{json.dumps(json.loads(choice.model_dump_json()), indent=2, ensure_ascii=False)}"
                )

                parsed = json.loads(choice.content)

                for req in parsed.get("requests", []):
                    intent = req.get("intent")
                    entities = req.get("entities", {})
                    if isinstance(entities, str):
                        try:
                            entities = json.loads(entities)
                            agent_logger.info("[PARSE] Deserialized entities from string to dict")
                        except json.JSONDecodeError:
                            agent_logger.error(f"[PARSE] Failed to deserialize entities: {entities}")
                            continue

                    # INTENT FIX-UP
                    if intent == "add_expense" and (
                            entities.get("creditor") or _LOAN_RE.search(part_text)
                    ):
                        agent_logger.debug(
                            f"[PARSE] Auto-switch EXPENSE → BORROW for part {part_idx}"
                        )
                        intent = "borrow"
                        entities["wallet"] = "borrow"

                    entities["input_text"] = part_text

                    # Дефолты
                    if intent == "add_income":
                        entities = {
                            "amount": entities.get("amount", "0.0"),
                            "date": entities.get("date", datetime.now().strftime("%d.%m.%Y")),
                            "category_code": entities.get("category_code", ""),
                            "comment": entities.get("comment", "Доход"),
                            "input_text": part_text,
                        }
                    else:
                        entities.setdefault(
                            "wallet",
                            {
                                "add_expense": "project",
                                "borrow": "borrow",
                                "repay": "repay",
                            }.get(intent, ""),
                        )
                        entities.setdefault("coefficient", "1.0")
                        entities.setdefault("date", datetime.now().strftime("%d.%m.%Y"))
                        entities.setdefault("comment", "Операция")
                        entities.setdefault("creditor", "")
                        entities.setdefault("category_code", "")
                        entities.setdefault("chapter_code", "")
                        entities.setdefault("subcategory_code", "")

                    missing = await validate_entities(entities, api_client, intent)

                    state.requests.append(
                        {
                            "intent": intent,
                            "entities": entities,
                            "missing": missing,
                            "index": len(state.requests),
                        }
                    )

            except Exception as e:
                agent_logger.exception(f"[PARSE] LLM error on part {part_idx}: {e}")
                continue

        # Автоматическое сопоставление категорий для доходов
        for req in state.requests:
            if req["intent"] == "add_income":
                comment = req["entities"].get("comment", "").lower()
                categories = await api_client.get_incomes()
                matching_categories = [
                    cat for cat in categories
                    if comment in cat.name.lower() or any(word in cat.name.lower() for word in comment.split())
                ]
                if len(matching_categories) == 1:
                    req["entities"]["category_code"] = matching_categories[0].code
                    req["missing"] = [m for m in req["missing"] if m != "category_code"]
                    agent_logger.debug(
                        f"[PARSE] Automatically set category_code={matching_categories[0].code} "
                        f"for comment={comment}"
                    )
                elif len(matching_categories) > 1:
                    agent_logger.debug(
                        f"[PARSE] Multiple matching categories for comment={comment}: "
                        f"{[c.name for c in matching_categories]}"
                    )

        # Лог
        state.messages.append(
            {
                "role": "assistant",
                "content": json.dumps(state.requests, ensure_ascii=False),
            }
        )
        agent_logger.info(
            f"[PARSE] Parsed {len(state.requests)} requests total:\n"
            f"{json.dumps(state.requests, indent=2, ensure_ascii=False)}"
        )

        if not state.requests:
            state.output = {
                "messages": [
                    {
                        "text": "Не удалось распознать запрос. Уточните, пожалуйста.",
                        "request_indices": [],
                    }
                ],
                "output": [],
            }

        return state
