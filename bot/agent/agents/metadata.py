import json
from datetime import datetime, timedelta

from agent.utils import AgentState, agent_logger
from api_client import ApiClient
from config import BACKEND_URL


async def metadata_agent(state: AgentState) -> AgentState:
    """Validate entities against API metadata and filter relevant metadata."""
    agent_logger.info("[METADATA] Entering metadata_agent")

    # Initialize filtered metadata
    filtered_metadata = {
        "expenses": {},
        "incomes": {},
        "creditors": {},
        "date_cols": {},
    }

    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            # Fetch full metadata
            full_metadata = await api_client.get_metadata()
            if not full_metadata:
                agent_logger.error("[METADATA] API returned empty metadata")
                state.output = {
                    "messages": [
                        {"text": "Сервер не вернул метаданные. Попробуйте снова.", "request_indices": []}
                    ],
                    "output": [],
                }
                return state
            agent_logger.info(f"[METADATA] Fetched metadata: {len(full_metadata.get('expenses', {}))} sections")

            # Validate entities
            for i, action in enumerate(state.actions):
                request = state.requests[action["request_index"]]
                entities = request["entities"]
                missing = request["missing"]

                try:
                    # Validate entities based on intent
                    intent = request.get("intent")
                    if intent == "add_expense":
                        # Validate chapter_code
                        if "chapter_code" in missing or entities.get("chapter_code"):
                            # Filter only valid chapter entries (exclude non-dict items like total_row)
                            chapter_names = [
                                data["name"] for code, data in full_metadata["expenses"].items()
                                if isinstance(data, dict) and "name" in data
                            ]
                            chapter_codes = {
                                data["name"]: code for code, data in full_metadata["expenses"].items()
                                if isinstance(data, dict) and "name" in data
                            }
                            if entities.get("chapter_code"):
                                if entities["chapter_code"] in full_metadata["expenses"] and isinstance(
                                        full_metadata["expenses"][entities["chapter_code"]], dict
                                ):
                                    if "chapter_code" in missing:
                                        missing.remove("chapter_code")
                                else:
                                    match, score = fuzzy_match(entities["chapter_code"], chapter_names)
                                    if score > 0.9:
                                        entities["chapter_code"] = chapter_codes[match]
                                        if "chapter_code" in missing:
                                            missing.remove("chapter_code")
                                    else:
                                        missing.append("chapter_code")
                                        entities["chapter_code"] = None

                        # Validate category_code
                        if (
                                ("category_code" in missing or entities.get("category_code"))
                                and entities.get("chapter_code")
                                and entities["chapter_code"] in full_metadata["expenses"]
                                and isinstance(full_metadata["expenses"][entities["chapter_code"]], dict)
                        ):
                            categories = full_metadata["expenses"][entities["chapter_code"]]["cats"]
                            category_names = [data["name"] for code, data in categories.items()]
                            category_codes = {data["name"]: code for code, data in categories.items()}
                            if entities.get("category_code"):
                                if entities["category_code"] in categories:
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
                        if (
                                ("subcategory_code" in missing or entities.get("subcategory_code"))
                                and entities.get("chapter_code")
                                and entities.get("category_code")
                                and entities["chapter_code"] in full_metadata["expenses"]
                                and isinstance(full_metadata["expenses"][entities["chapter_code"]], dict)
                                and entities["category_code"]
                                in full_metadata["expenses"][entities["chapter_code"]]["cats"]
                        ):
                            subcategories = full_metadata["expenses"][entities["chapter_code"]]["cats"][
                                entities["category_code"]
                            ]["subs"]
                            subcategory_names = [
                                data["name"] for code, data in subcategories.items() if data["name"]
                            ]
                            subcategory_codes = {
                                data["name"]: code
                                for code, data in subcategories.items()
                                if data["name"]
                            }
                            if entities.get("subcategory_code"):
                                if entities["subcategory_code"] in subcategories:
                                    if "subcategory_code" in missing:
                                        missing.remove("subcategory_code")
                                else:
                                    match, score = fuzzy_match(
                                        entities["subcategory_code"], subcategory_names
                                    )
                                    if score > 0.9:
                                        entities["subcategory_code"] = subcategory_codes[match]
                                        if "subcategory_code" in missing:
                                            missing.remove("subcategory_code")
                                    else:
                                        missing.append("subcategory_code")
                                        entities["subcategory_code"] = None

                    elif intent == "add_income":
                        # Validate category_code for income
                        if "category_code" in missing or entities.get("category_code") or entities.get("comment"):
                            category_names = [
                                data["name"] for code, data in full_metadata["income"]["cats"].items()
                            ]
                            category_codes = {
                                data["name"]: code
                                for code, data in full_metadata["income"]["cats"].items()
                            }
                            # Try to match category_code if provided
                            if entities.get("category_code"):
                                if entities["category_code"] in full_metadata["income"]["cats"]:
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
                            # If category_code is empty, try to match comment
                            elif entities.get("comment"):
                                match, score = fuzzy_match(entities["comment"], category_names)
                                if score > 0.9:
                                    entities["category_code"] = category_codes[match]
                                    if "category_code" in missing:
                                        missing.remove("category_code")
                                else:
                                    if "category_code" not in missing:
                                        missing.append("category_code")
                                    entities["category_code"] = None

                    elif intent in ["borrow", "repay"]:
                        # Validate creditor
                        if "creditor" in missing or entities.get("creditor"):
                            creditor_names = list(full_metadata["creditors"].keys())
                            if entities.get("creditor"):
                                if entities["creditor"] in full_metadata["creditors"]:
                                    if "creditor" in missing:
                                        missing.remove("creditor")
                                else:
                                    match, score = fuzzy_match(entities["creditor"], creditor_names)
                                    if score > 0.9:
                                        entities["creditor"] = match
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
                                entities["date"] = (datetime.now() - timedelta(days=2)).strftime(
                                    "%d.%m.%Y"
                                )
                            elif entities["date"].lower() == "вчера":
                                entities["date"] = (datetime.now() - timedelta(days=1)).strftime(
                                    "%d.%m.%Y"
                                )
                            elif entities["date"].lower() == "сегодня":
                                entities["date"] = datetime.now().strftime("%d.%m.%Y")
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
                    agent_logger.info(f"[METADATA] Validated request {action['request_index']}")
                    agent_logger.debug(
                        f"[METADATA] Validated request {action['request_index']}: "
                        f"entities={json.dumps(entities, ensure_ascii=False)}, missing={missing}"
                    )
                except Exception as e:
                    agent_logger.exception(f"[METADATA] Error validating entities: {e}")
                    state.output = {
                        "messages": [
                            {
                                "text": "Сервер временно недоступен. Попробуйте снова.",
                                "request_indices": [],
                            }
                        ],
                        "output": [],
                    }
                    return state

            # Filter metadata based on validated entities
            for request in state.requests:
                entities = request.get("entities", {})
                intent = request.get("intent")

                if intent == "add_expense":
                    chapter_code = entities.get("chapter_code")
                    category_code = entities.get("category_code")
                    subcategory_code = entities.get("subcategory_code")
                    date = entities.get("date")

                    if (
                            chapter_code
                            and chapter_code in full_metadata["expenses"]
                            and isinstance(full_metadata["expenses"][chapter_code], dict)
                            and full_metadata["expenses"][chapter_code]["name"]
                    ):
                        chapter_data = full_metadata["expenses"][chapter_code]
                        filtered_metadata["expenses"][chapter_code] = {
                            "name": chapter_data["name"],
                            "row": chapter_data.get("row"),
                            "cats": {},
                        }

                        if (
                                category_code
                                and category_code in chapter_data["cats"]
                                and chapter_data["cats"][category_code]["name"]
                        ):
                            category_data = chapter_data["cats"][category_code]
                            filtered_metadata["expenses"][chapter_code]["cats"][category_code] = {
                                "name": category_data["name"],
                                "row": category_data.get("row"),
                                "subs": {},
                            }

                            if (
                                    subcategory_code
                                    and subcategory_code in category_data["subs"]
                                    and category_data["subs"][subcategory_code]["name"]
                            ):
                                subcategory_data = category_data["subs"][subcategory_code]
                                filtered_metadata["expenses"][chapter_code]["cats"][category_code][
                                    "subs"
                                ][subcategory_code] = {
                                    "name": subcategory_data["name"],
                                    "row": subcategory_data.get("row"),
                                }

                elif intent == "add_income":
                    category_code = entities.get("category_code")
                    date = entities.get("date")

                    if (
                            category_code
                            and category_code in full_metadata["income"]["cats"]
                            and full_metadata["income"]["cats"][category_code]["name"]
                    ):
                        category_data = full_metadata["income"]["cats"][category_code]
                        filtered_metadata["incomes"][category_code] = {
                            "name": category_data["name"],
                            "row": category_data.get("row"),
                        }

                elif intent in ["borrow", "repay"]:
                    creditor = entities.get("creditor")
                    date = entities.get("date")

                    if creditor and creditor in full_metadata["creditors"]:
                        filtered_metadata["creditors"][creditor] = full_metadata["creditors"][
                            creditor
                        ]

                elif intent == "get_analytics":
                    date = entities.get("date", "")
                    valid_periods = ['day', 'month', 'custom', 'overview']
                    if entities.get("period") not in valid_periods:
                        missing.append("period")
                        entities["period"] = None
                    else:
                        period = entities["period"]


                    valid_levels = ['section', 'category', 'subcategory']
                    if entities.get("level") not in valid_levels:
                        missing.append("level")
                        entities["level"] = None
                    else:
                        level = entities["level"]

                    for field in ["zero_suppress", "include_comments", "include_month_summary"]:
                        if field not in [True, False]:
                            missing.append(field)
                            entities[field] = False
                            if field not in missing:
                                missing.append(field)

                    if period == "day":
                        if date:
                            try:
                                if date.lower() in ["позавчера", "вчера", "сегодня"]:
                                    if date.lower() == "позавчера":
                                        entities["date"] = (datetime.now() - timedelta(days=2)).strftime(
                                            "%d.%m.%Y"
                                        )
                                    elif date.lower() == "вчера":
                                        entities["date"] = (datetime.now() - timedelta(days=1)).strftime(
                                            "%d.%m.%Y"
                                        )
                                    elif date.lower() == "сегодня":
                                        entities["date"] = datetime.now().strftime("%d.%m.%Y")
                                    else:
                                        datetime.strptime(date, "%d.%m.%Y")

                                    if "date" in missing:
                                        missing.remove("date")
                            except ValueError:
                                missing.append("date")
                                entities["date"] = None
                        else:
                            missing.append("date")
                            entities["date"] = None

                    elif period == "month":
                        ym = entities.get("ym")
                        if ym:
                            try:
                                datetime.strptime(ym, "%Y-%m")
                                if "ym" in missing:
                                    missing.remove("ym")
                            except ValueError:
                                missing.append("ym")
                                entities["ym"] = None
                        else:
                            missing.append("ym")
                            entities["ym"] = None

                    elif period == "custom":
                        start_date = entities.get("start_date")
                        end_date = entities.get("end_date")
                        if start_date and end_date:
                            try:
                                datetime.strptime(start_date, "%d.%m.%Y")
                                datetime.strptime(end_date, "%d.%m.%Y")
                                if "start_date" in missing:
                                    missing.remove("start_date")
                                if "end_date" in missing:
                                    missing.remove("end_date")
                            except ValueError:
                                missing.extend(["start_date", "end_date"])
                                entities["start_date"] = None
                                entities["end_date"] = None
                        else:
                            missing.extend(["start_date" if not start_date else "", "end_date" if not end_date else ""])
                            missing = [m for m in missing if m]
                            entities["start_date"] = None if not start_date else entities["start_date"]
                            entities["end_date"] = None if not end_date else entities["end_date"]

                    elif period == "overview":
                        pass



                if date and date in full_metadata["date_cols"]:
                    filtered_metadata["date_cols"][date] = full_metadata["date_cols"][date]

            # Update state.metadata with filtered metadata
            state.metadata = filtered_metadata
            state.messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "entities_validated": [
                                req["entities"] for req in state.requests
                            ],
                            "metadata_filtered": filtered_metadata,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            agent_logger.info("[METADATA] Metadata agent completed")
        except Exception as e:
            agent_logger.exception(f"[METADATA] Error in metadata_agent: {e}")
            state.output = {
                "messages": [
                    {"text": "Ошибка при обработке метаданных. Попробуйте снова.", "request_indices": []}
                ],
                "output": [],
            }
            return state
    return state