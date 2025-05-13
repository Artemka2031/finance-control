import asyncio
import os
from dotenv import load_dotenv
from .agent.agent import run_agent
from .api_client import ApiClient
from .config import BOT_TOKEN
from .utils.logging import configure_logger

# Load environment variables
load_dotenv()

# Check environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set in .env file. Please add it to P:\\Python\\finance-control\\.env")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env file")

# Configure test logger
logger = configure_logger("[AGENT_TEST]", "green")

async def test_agent():
    """Test the agent logic with predefined inputs and log results to console."""
    logger.info("Initializing API client")
    api_client = ApiClient()
    try:
        test_inputs = [
            "Потратил 3000 на еду вчера",
            "Взял в долг 5000 у Наташи на кофе",
            "3000 на кофейни и 2000 на такси",
            "Вернул долг 2000 Наташе",
            "Потратил 1000 на протеин 05.05.2025"
        ]

        for input_text in test_inputs:
            logger.info(f"Testing input: {input_text}")
            try:
                result = await run_agent(input_text)
                logger.debug(f"Agent output: {result}")
                for msg in result.get("messages", []):
                    logger.info(f"Message: {msg['text']}")
                    if msg.get("keyboard"):
                        logger.debug(f"Keyboard: {msg['keyboard']}")
                for out in result.get("output", []):
                    logger.info(f"Output entities: {out['entities']}")
            except Exception as e:
                logger.error(f"Error processing input '{input_text}': {e}")
            logger.info("-" * 50)
    finally:
        logger.info("Closing API client")
        await api_client.close()

async def main():
    """Run the agent tests."""
    logger.info("Running agent tests")
    try:
        await test_agent()
        logger.info("Tests completed successfully")
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        raise

if __name__ == "__main__":
    logger.info("Starting agent test application")
    asyncio.run(main())