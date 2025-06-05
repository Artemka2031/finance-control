import json
import re
from ..config import BACKEND_URL
from ..prompts import ANALYTIC_PROMPT
from ..utils import AgentState, openai_client, agent_logger
from ...api_client import ApiClient

async def expense_analysis_agent(state: AgentState) -> AgentState:
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        agent_logger.info("[EXPENSE_ANALYSIS] Entering analytic_agent")

        try:
            for i, action in enumerate(state.actions):
                request = state.requests[action["request_index"]]
                intent = request["intent"]
                entities = request["entities"]

                if intent != "get_analytics" or action.get("needs_clarification"):
                    agent_logger.debug(f"[EXPENSE_ANALYSIS] Skipping request {action['request_index']}")
                    continue

                agent_logger.debug(f"[EXPENSE_ANALYSIS] Processing request: {action['request_index']}")

                period = entities["period"]
                analytics_data = None

                if period == "day":
                    analytics_data = await api_client.day_breakdown(
                        date=entities["date"],
                        level=entities["level"],
                        zero_suppress=entities["zero_suppress"],
                        include_month_summary=entities["include_month_summary"],
                        include_comments=entities["include_comments"]
                    )
                elif period == "month":
                    analytics_data = await api_client.month_totals(
                        ym=entities["ym"],
                        level=entities["level"],
                        zero_suppress=entities["zero_suppress"],
                        include_balances=entities["include_balances"],
                    )
                elif period == "custom":
                    analytics_data = await api_client.period_expense_summary(
                        start_date = entities["start_date"],
                        end_date = entities["end_date"],
                        level = entities["level"],
                        zero_suppress = entities["zero_suppress"],
                        include_comments = entities["include_comments"]
                    )
                elif period == "overview":
                    analytics_data = await api_client.months_overview(
                        level = entities["level"],
                        zero_suppress = entities["zero_suppress"],
                        include_balances = entities["include_balances"],
                    )

                # if not analytics_data or not analytics_data.get("expense", {}).get("tree"):
                #     #period_text = f"с {start_date} по {end_date}" if period == "custom" else period
                #
                #     agent_logger.warning(f"[EXPENSE_ANALYSIS] No expense data for period={period}")
                #     state.output.setdefault("messages", []).append({
                #         "text": "Недостаточно данных для анализа. Укажите другой период.",
                #         "request_indices": [action["request_index"]]
                #     })
                #     continue

                if entities["include_comments"]:
                    for section in analytics_data["expense"]["tree"].values():
                        for cat in section.get("cats", {}).values():
                            for subcat in cat.get("subs", {}).values():
                                if subcat.get("comment"):
                                    pattern = r"✨(\d+\.\d{2})\s+(.+?)✨"
                                    transactions = re.findall(pattern, subcat["comment"])
                                    subcat["transactions"] = [
                                        {"amount": float(amount), "description": desc}
                                        for amount, desc in transactions
                                    ]
                llm_input = json.dumps(
                    {
                        "analytics_data": analytics_data,
                        "entities": entities,
                    }, ensure_ascii=False
                )

                try:
                    resp = await openai_client.chat.completions.create(
                        model="gpt-4.1-mini",
                        messages=[
                            {"role": "system", "content": ANALYTIC_PROMPT},
                            {"role": "user", "content": llm_input}
                        ],
                        response_format={"type": "json_object"},
                    )
                    analysis_text = json.loads(resp.choices[0].message.content).get(
                        "text", "Ошибка анализа данных."
                    )

                    agent_logger.debug(f"[EXPENSE_ANALYSIS] LLM response: {analysis_text}")

                    state.output.setdefault("messages", []).append({
                        "text": analysis_text,
                        "request_indices": [action["request_index"]]
                    })
                    action["ready_for_output"] = True
                    state.actions[i] = action

                except Exception as e:
                    agent_logger.error(f"[EXPENSE_ANALYSIS] LLM error: {e}")
                    state.output.setdefault("messages", []).append({
                        "text": "Ошибка анализа данных. Попробуйте снова.",
                        "request_indices": [action["request_index"]]
                    })
                    action["ready_for_output"] = True
                    state.actions[i] = action

        except Exception as e:
            agent_logger.exception(f"[EXPENSE_ANALYSIS] Error: {e}")
            state.output = {
                "messages": [{"text": "Ошибка анализа расходов. Попробуйте снова.", "request_indices": []}],
                "output": []
            }

        return state
