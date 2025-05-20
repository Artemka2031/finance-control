# Bot/agent/agents/tools.py
import json

from ..utils import AgentState, agent_logger, validate_category


async def tools_agent(state: AgentState) -> AgentState:
    """Handle tool calls."""
    agent_logger.info("[TOOLS] Entering tools_agent")
    last_message = state.messages[-1]
    if last_message.get("tool_calls"):
        for tool_call in last_message["tool_calls"]:
            if tool_call["function"]["name"] == "validate_category":
                args = tool_call["function"]["arguments"]
                agent_logger.info(f"[TOOLS] Calling validate_category: {args}")
                result = await validate_category(
                    category_name=args["category_name"],
                    chapter_code=args["chapter_code"]
                )
                agent_logger.info("[TOOLS] Received validate_category response")
                agent_logger.debug(f"[TOOLS] Validate_category result: {result}")
                state.messages.append({
                    "role": "tool",
                    "content": json.dumps(result),
                    "tool_call_id": tool_call["id"]
                })
                if result["success"]:
                    for req in state.requests:
                        req["entities"]["category_code"] = result["category_code"]
                        if "category_code" in req["missing"]:
                            req["missing"].remove("category_code")
                        if "subcategory_code" not in req["missing"]:
                            req["missing"].append("subcategory_code")
                        agent_logger.info(f"[TOOLS] Updated request: {json.dumps(req, ensure_ascii=False)}")
    return state