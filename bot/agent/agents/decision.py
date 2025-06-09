import json

from openai import AsyncOpenAI

from agent.prompts import get_decision_prompt
from agent.utils import AgentState, agent_logger
from api_client import ApiClient
from config import BACKEND_URL, OPENAI_API_KEY


async def decision_agent(state: AgentState) -> AgentState:
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        agent_logger.info("[DECISION] Entering decision_agent")
        actions = []
        combine_responses = True
        metadata = state.metadata or {}

        # Initialize OpenAI client
        agent_logger.debug(
            f"Initializing OpenAI client with API key: {'*' * len(OPENAI_API_KEY[:-4]) + OPENAI_API_KEY[-4:]}")
        try:
            openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        except Exception as e:
            agent_logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

        # Prepare input for LLM
        requests = []
        for req in state.requests:
            entities = req.get("entities", {})
            if isinstance(entities, str):
                try:
                    entities = json.loads(entities)
                    req["entities"] = entities
                    agent_logger.info("[DECISION] Deserialized entities from string to dict")
                except json.JSONDecodeError:
                    agent_logger.error(f"[DECISION] Failed to deserialize entities: {entities}")
                    continue
            requests.append({
                "intent": req["intent"],
                "entities": entities,
                "missing": req.get("missing", [])
            })

        try:
            # Call LLM to get decision
            prompt = get_decision_prompt(requests)
            response = await openai_client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=512
            )
            response_content = response.choices[0].message.content
            response_data = json.loads(response_content)
            agent_logger.info("[DECISION] Received OpenAI response")
            agent_logger.debug(f"[DECISION] OpenAI response: {json.dumps(response_data, indent=2, ensure_ascii=False)}")

            actions = response_data.get("actions", [])
            combine_responses = response_data.get("combine_responses", True)

            # Validate response
            if len(actions) != len(state.requests):
                agent_logger.error("[DECISION] Invalid LLM response: action count mismatch")
                actions = []
                combine_responses = False
                for idx, request in enumerate(state.requests):
                    actions.append({
                        "request_index": idx,
                        "needs_clarification": bool(request.get("missing", [])),
                        "clarification_field": request.get("missing", [None])[0],
                        "ready_for_output": not bool(request.get("missing", []))
                    })

            # Validate metadata
            for action in actions:
                idx = action["request_index"]
                request = state.requests[idx]
                intent = request["intent"]
                entities = request["entities"]

                if intent == "add_income":
                    categories = await api_client.get_incomes()
                    if (
                            entities.get("category_code")
                            and entities["category_code"] not in {cat.code for cat in categories}
                    ):
                        request["missing"] = request.get("missing", []) + ["category_code"]
                        action["needs_clarification"] = True
                        action["clarification_field"] = "category_code"
                        action["ready_for_output"] = False
                elif intent in ["add_expense", "borrow"]:
                    chapter_code = entities.get("chapter_code")
                    category_code = entities.get("category_code")
                    if chapter_code and chapter_code not in metadata.get("expenses", {}):
                        request["missing"] = request.get("missing", []) + ["chapter_code"]
                        action["needs_clarification"] = True
                        action["clarification_field"] = "chapter_code"
                        action["ready_for_output"] = False
                    elif chapter_code and category_code and category_code not in metadata.get("expenses", {}).get(
                            chapter_code, {}).get("cats", {}):
                        request["missing"] = request.get("missing", []) + ["category_code"]
                        action["needs_clarification"] = True
                        action["clarification_field"] = "category_code"
                        action["ready_for_output"] = False

        except Exception as e:
            agent_logger.exception(f"[DECISION] LLM processing failed: {e}")
            # Fallback to basic logic
            required_fields = {
                "add_income": ["category_code", "date", "amount", "comment"],
                "add_expense": ["chapter_code", "category_code", "subcategory_code", "date", "amount", "wallet"],
                "borrow": ["chapter_code", "category_code", "subcategory_code", "date", "amount", "wallet", "creditor",
                           "coefficient"],
                "repay": ["date", "amount", "wallet", "creditor"]
            }
            for idx, request in enumerate(state.requests):
                missing = request.get("missing", [])
                intent = request["intent"]
                entities = request["entities"]
                for field in required_fields.get(intent, []):
                    if field not in entities or entities[field] in [None, "", []]:
                        if field not in missing:
                            missing.append(field)
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
        state.requests = [dict(req, missing=req.get("missing", [])) for req in state.requests]
        agent_logger.info(f"[DECISION] Generated {len(actions)} actions: {actions}, combine: {combine_responses}")

        response = {
            "actions": actions,
            "combine_responses": combine_responses
        }
        state.messages.append({"role": "assistant", "content": json.dumps(response, ensure_ascii=False)})
        agent_logger.info("[DECISION] Generated response")
        agent_logger.debug(f"[DECISION] Response: {json.dumps(response, indent=2, ensure_ascii=False)}")

        return state
