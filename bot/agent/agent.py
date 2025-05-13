"""
Functional-API версия финансового агента.
Запускается так:
    result = await expense_workflow.ainvoke({"input_text": "Потратил 3000 на еду вчера"})
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.func import entrypoint, task
from openai import AsyncOpenAI

from .config import OPENAI_API_KEY, BACKEND_URL
from .prompts import get_parse_prompt, DECISION_PROMPT, RESPONSE_PROMPT
from .utils import configure_logger, fuzzy_match
from ..api_client import ApiClient

logger = configure_logger("[FUNC_AGENT]", "blue")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
checkpointer = MemorySaver()


# ────────────────────────────── helpers ────────────────────────────────────────
async def _llm_json(prompt: str) -> Dict[str, Any]:
    """Call OpenAI in JSON-mode and return parsed content."""
    resp = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content.strip())

def _short(obj: Any, n: int = 100) -> str:
    txt = json.dumps(obj, ensure_ascii=False)[:n]
    return txt + ("…" if len(txt) == n else "")


# ────────────────────────────── tasks ──────────────────────────────────────────
@task
async def parse_task(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"[parse_task] input = {_short(state)}")
    prompt = get_parse_prompt(state["input_text"])
    try:
        raw = await _llm_json(prompt)
        requests = [{"intent": r.get("intent"),
                     "entities": r.get("entities", {}),
                     "missing": r.get("missing", [])} for r in raw.get("requests", [])]
        if not requests:
            return {"output": {"messages": [{
                "text": "Не удалось распознать запрос. Уточните, пожалуйста.",
                "request_indices": []}], "output": []}}
        logger.info(f"[parse_task] output = {_short(requests)}")
        return {"requests": requests}
    except Exception as e:
        logger.error(f"parse_task: {e}")
        return {"output": {"messages": [{
            "text": "Не удалось обработать запрос. Попробуйте снова.",
            "request_indices": []}], "output": []}}


@task
async def decision_task(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("requests"):
        return {}
    prompt = DECISION_PROMPT + \
             f"\n\n**Входные данные**:\n{json.dumps({'requests': state['requests']}, ensure_ascii=False)}"
    try:
        res = await _llm_json(prompt)
        actions = [{"request_index": a.get("request_index", 0),
                    "needs_clarification": a.get("needs_clarification", False),
                    "ready_for_output": a.get("ready_for_output", False)}
                   for a in res.get("actions", [])]
        return {"actions": actions,
                "combine_responses": res.get("combine_responses", False)}
    except Exception as e:
        logger.error(f"decision_task: {e}")
        return {"output": {"messages": [{
            "text": "Ошибка при обработке. Попробуйте снова.",
            "request_indices": []}], "output": []}}


@task
async def metadata_task(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("actions"):
        return {}
    api = ApiClient(base_url=BACKEND_URL)

    # локальные кэши (in-memory)
    sec_cache, cat_cache, subcat_cache, cred_cache = {}, {}, {}, {}

    updated_requests = state["requests"].copy()
    updated_actions = state["actions"].copy()

    for i, act in enumerate(state["actions"]):
        if not act["needs_clarification"]:
            continue
        req = updated_requests[act["request_index"]]
        ent, miss = req["entities"], req["missing"]

        # --- секции ---
        if not sec_cache:
            sec_cache = {s.name: s.code for s in await api.get_sections()}
        if ent.get("chapter_code"):
            match, score = fuzzy_match(ent["chapter_code"], list(sec_cache))
            if score:
                ent["chapter_code"] = sec_cache[match]
                miss = [m for m in miss if m != "chapter_code"]

        # --- категории ---
        if ent.get("chapter_code") and ent.get("category_code"):
            if ent["chapter_code"] not in cat_cache:
                cat_cache[ent["chapter_code"]] = {
                    c.name: c.code for c in await api.get_categories(ent["chapter_code"])}
            match, score = fuzzy_match(ent["category_code"], list(cat_cache[ent["chapter_code"]]))
            if score:
                ent["category_code"] = cat_cache[ent["chapter_code"]][match]
                miss = [m for m in miss if m != "category_code"]

        # --- подкатегории ---
        if all(ent.get(k) for k in ("chapter_code", "category_code", "subcategory_code")):
            key = f"{ent['chapter_code']}/{ent['category_code']}"
            if key not in subcat_cache:
                subcat_cache[key] = {
                    s.name: s.code
                    for s in await api.get_subcategories(ent["chapter_code"], ent["category_code"])
                }
            match, score = fuzzy_match(ent["subcategory_code"], list(subcat_cache[key]))
            if score:
                ent["subcategory_code"] = subcat_cache[key][match]
                miss = [m for m in miss if m != "subcategory_code"]

        # --- кредиторы ---
        if ent.get("wallet") in ("borrow", "repay") and ent.get("creditor"):
            if not cred_cache:
                cred_cache = {c.name: c.code for c in await api.get_creditors()}
            match, score = fuzzy_match(ent["creditor"], list(cred_cache))
            if score:
                ent["creditor"] = cred_cache[match]
                miss = [m for m in miss if m != "creditor"]

        # --- дата ---
        if not ent.get("date"):
            ent["date"] = datetime.now().strftime("%d.%m.%Y")
        elif ent["date"].lower() == "вчера":
            ent["date"] = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")

        ent.setdefault("wallet", "project")
        ent.setdefault("coefficient", 1.0)

        req["entities"], req["missing"] = ent, miss
        act["needs_clarification"] = bool(miss)
        act["ready_for_output"] = not bool(miss)

        updated_requests[act["request_index"]] = req
        updated_actions[i] = act

    await api.close()
    return {"requests": updated_requests, "actions": updated_actions}


@task
async def response_task(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("actions"):
        return {}
    prompt = RESPONSE_PROMPT + (
        f"\n\n**Входные данные**:\n{json.dumps({'actions': state['actions'],
                                                'requests': state['requests'],
                                                'combine_responses': state.get('combine_responses', False)},
                                               ensure_ascii=False)}"
    )
    try:
        res = await _llm_json(prompt)
        return {"output": {"messages": res.get("messages", []),
                           "output": res.get("output", [])}}
    except Exception as e:
        logger.error(f"response_task: {e}")
        return {"output": {"messages": [{
            "text": "Ошибка при формировании ответа. Попробуйте снова.",
            "request_indices": []}], "output": []}}


# ─────────────────────────── entrypoint ────────────────────────────────────────
@entrypoint(checkpointer=checkpointer)
async def expense_workflow(payload: Dict[str, str]) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "input_text": payload["input_text"],
        "requests": [],  # ← добавили
        "actions": [],  # ← добавили
        "combine_responses": False,
        "output": {},  # ← добавили
    }
    logger.info(f"[ENTRY] input_text='{state['input_text']}'")

    for _task in (parse_task, decision_task, metadata_task, response_task):
        logger.info(f"[BEFORE] {_task.__name__} | state keys = {list(state.keys())}")
        result = await _task(state)
        logger.info(f"[AFTER ] {_task.__name__} -> {_short(result)}")
        state.update(result)

    logger.info(f"[DONE] output = {_short(state.get('output', {}))}")
    return state.get("output", {})

# ─────────────────────────── helper для бота ───────────────────────────────────
async def run_agent(input_text: str) -> Dict[str, Any]:
    """Удобная обёртка для TG-роутера— генерирует thread_id автоматически."""
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    try:
        return await expense_workflow.ainvoke({"input_text": input_text}, config=config)
    except Exception:
        logger.exception("run_agent failed")  # печатает stacktrac
        return {"messages": [...], "output": []}
