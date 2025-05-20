# Bot/agent/agents/metadata.py
import json
from datetime import datetime, timedelta

from ...api_client import ApiClient
from ..config import BACKEND_URL
from ..utils import AgentState, agent_logger, section_cache, category_cache, subcategory_cache, creditor_cache, \
    fuzzy_match


async def metadata_agent(state: AgentState) -> AgentState:
    """Validate entities against API and filter metadata."""
    agent_logger.info("[METADATA] Entering metadata_agent")

    # Initialize filtered metadata
    filtered_metadata = {
        "expenses": {},
        "date_cols": {},
    }

    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            # Validate entities
            for i, action in enumerate(state.actions):
                if not action.get("needs_clarification"):
                    continue
                request = state.requests[action["request_index"]]
                entities = request["entities"]
                missing = request["missing"]

                try:
                    # Cache sections
                    if not section_cache:
                        section_cache.extend(await api_client.get_sections())
                        if not section_cache:
                            agent_logger.error("[METADATA] API returned empty sections")
                            state.output = {
                                "messages": [
                                    {"text": "Сервер не вернул разделы. Попробуйте снова.", "request_indices": []}],
                                "output": []
                            }
                            return state
                        agent_logger.info(f"[METADATA] Fetched {len(section_cache)} sections")
                        agent_logger.debug(
                            f"[METADATA] Fetched sections: {[{'code': sec.code, 'name': sec.name} for sec in section_cache]}")
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
                                agent_logger.error(
                                    f"[METADATA] No categories for chapter_code: {entities['chapter_code']}")
                                state.output = {
                                    "messages": [
                                        {"text": f"Нет категорий для раздела {entities['chapter_code']}.",
                                         "request_indices": []}],
                                    "output": []
                                }
                                return state
                            agent_logger.info(
                                f"[METADATA] Fetched {len(category_cache[entities['chapter_code']])} categories")
                            agent_logger.debug(
                                f"[METADATA] Fetched categories for {entities['chapter_code']}: {[{'code': cat.code, 'name': cat.name} for cat in category_cache[entities['chapter_code']]]}")
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
                                agent_logger.warning(f"[METADATA] No subcategories for {cat_key}")
                            agent_logger.info(
                                f"[METADATA] Fetched {len(subcategory_cache[cat_key])} subcategories")
                            agent_logger.debug(
                                f"[METADATA] Fetched subcategories for {cat_key}: {[{'code': sub.code, 'name': sub.name} for sub in subcategory_cache[cat_key]]}")
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
                            creditor_cache.extend(await api_client.get_creditors())
                            agent_logger.info(f"[METADATA] Fetched {len(creditor_cache)} creditors")
                            agent_logger.debug(
                                f"[METADATA] Fetched creditors: {[{'code': cred.code, 'name': cred.name} for cred in creditor_cache]}")
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
                    agent_logger.info(
                        f"[METADATA] Validated request {action['request_index']}")
                    agent_logger.debug(
                        f"[METADATA] Validated request {action['request_index']}: entities={json.dumps(entities, ensure_ascii=False)}, missing={missing}")
                except Exception as e:
                    agent_logger.exception(f"[METADATA] Error validating entities: {e}")
                    state.output = {
                        "messages": [{"text": "Сервер временно недоступен. Попробуйте снова.", "request_indices": []}],
                        "output": []
                    }
                    return state

            # Filter metadata based on validated entities
            full_metadata = state.metadata
            for request in state.requests:
                if request.get("intent") == "add_expense":
                    entities = request.get("entities", {})
                    chapter_code = entities.get("chapter_code")
                    category_code = entities.get("category_code")
                    subcategory_code = entities.get("subcategory_code")
                    date = entities.get("date")

                    # Filter expenses metadata
                    if chapter_code and chapter_code in full_metadata.get("expenses", {}):
                        chapter_data = full_metadata["expenses"][chapter_code]
                        filtered_metadata["expenses"][chapter_code] = {
                            "name": chapter_data.get("name"),
                            "row": chapter_data.get("row"),
                            "cats": {}
                        }

                        # Filter category
                        if category_code and category_code in chapter_data.get("cats", {}):
                            category_data = chapter_data["cats"][category_code]
                            filtered_metadata["expenses"][chapter_code]["cats"][category_code] = {
                                "name": category_data.get("name"),
                                "row": category_data.get("row"),
                                "subs": {}
                            }

                            # Filter subcategory
                            if subcategory_code and subcategory_code in category_data.get("subs", {}):
                                subcategory_data = category_data["subs"][subcategory_code]
                                filtered_metadata["expenses"][chapter_code]["cats"][category_code]["subs"][
                                    subcategory_code] = {
                                    "name": subcategory_data.get("name"),
                                    "row": subcategory_data.get("row")
                                }

                    # Filter date_cols
                    if date and date in full_metadata.get("date_cols", {}):
                        filtered_metadata["date_cols"][date] = full_metadata["date_cols"][date]

            # Update state.metadata with filtered metadata
            state.metadata = filtered_metadata
            state.messages.append({"role": "assistant", "content": json.dumps(
                {"entities_validated": state.requests, "metadata_filtered": filtered_metadata})})
            agent_logger.info("[METADATA] Metadata agent completed")
        except Exception as e:
            agent_logger.exception(f"[METADATA] Error in metadata_agent: {e}")
            state.output = {
                "messages": [{"text": "Ошибка при обработке метаданных. Попробуйте снова.", "request_indices": []}],
                "output": []
            }
            return state
    return state