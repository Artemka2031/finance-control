import pytest
import asyncio
from ...api_client import ApiClient
from ..agent import run_agent
from ...utils.logging import configure_logger

logger = configure_logger("[AGENT_TEST]", "yellow")

@pytest.mark.asyncio
async def test_agent_parsing():
    api_client = ApiClient()
    test_cases = [
        {
            "input": "Потратил 3000 на еду вчера",
            "expected_intent": "add_expense",
            "expected_missing": ["category_code", "subcategory_code"]
        },
        {
            "input": "Взял в долг 5000 у Наташи на кофе",
            "expected_intent": "borrow",
            "expected_missing": ["creditor"]
        },
        {
            "input": "3000 на кофейни и 2000 на такси",
            "expected_intent": "add_expense",
            "expected_missing": ["subcategory_code"]
        }
    ]

    for case in test_cases:
        logger.info(f"Testing input: {case['input']}")
        result = await run_agent(case['input'])
        assert result["messages"] or result["output"], f"No output for input: {case['input']}"
        for request in result.get("output", []) + [m for msg in result.get("messages", []) for m in msg["request_indices"]]:
            assert request["intent"] == case["expected_intent"], f"Wrong intent for {case['input']}"
            assert set(request["missing"]) == set(case["expected_missing"]), f"Wrong missing fields for {case['input']}"
        logger.debug(f"Test passed for input: {case['input']}")

    await api_client.close()