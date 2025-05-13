import asyncio
import json
from loguru import logger
from bot.agent.agent import run_agent
from bot.api_client import ApiClient
from bot.utils.logging import configure_logger

logger = configure_logger("[TEST]", "white")


async def test_api_metadata():
    """Test API connectivity and retrieve metadata."""
    logger.info("Testing API connectivity")
    api_client = ApiClient(base_url="http://localhost:8000")
    try:
        metadata = await api_client.get_metadata()
        if "detail" in metadata:
            logger.error(f"Failed to retrieve metadata: {metadata['detail']}")
            return False
        logger.info(f"Metadata retrieved successfully")
        return True
    except Exception as e:
        logger.exception(f"API test failed: {e}")
        return False
    finally:
        await api_client.close()


async def test_agent():
    logger.info("Initializing API client")
    api_client = ApiClient(base_url="http://localhost:8000")
    try:
        api_ok = await test_api_metadata()
        if not api_ok:
            logger.error("Skipping agent tests due to API failure")
            return

        test_inputs = ["Потратил 3000 на еду вчера"]
        state = None

        for input_text in test_inputs:
            logger.info(f"Testing input: {input_text}")
            while True:
                result = await run_agent(input_text, interactive=True, selection=state)
                logger.debug(f"Agent output: {json.dumps(result, indent=2, ensure_ascii=False)}")

                try:
                    if not isinstance(result, dict) or "messages" not in result:
                        logger.error(f"Invalid result format for input '{input_text}': {result}")
                        break

                    for message in result.get("messages", []):
                        logger.info(f"Message: {message.get('text', 'No text')}")
                        if message.get("keyboard"):
                            logger.debug(f"Keyboard: {json.dumps(message['keyboard'], indent=2, ensure_ascii=False)}")
                            buttons = message["keyboard"]["inline_keyboard"][0]
                            print("\nВыберите опцию:")
                            for i, button in enumerate(buttons, 1):
                                print(f"{i}. {button['text']} ({button['callback_data']})")
                            choice = input("Введите номер опции (или 'q' для выхода): ")
                            if choice.lower() == 'q':
                                break
                            try:
                                choice_idx = int(choice) - 1
                                if 0 <= choice_idx < len(buttons):
                                    state = buttons[choice_idx]["callback_data"]
                                    logger.info(f"Selected: {state}")
                                else:
                                    logger.error("Неверный выбор")
                                    break
                            except ValueError:
                                logger.error("Введите число")
                                break
                    else:
                        break  # Нет клавиатуры, завершаем цикл
                except Exception as e:
                    logger.exception(f"Error processing input '{input_text}': {e}")
                    break

            logger.info("--------------------------------------------------")
    finally:
        logger.info("Closing API client")
        await api_client.close()


async def main():
    logger.info("Running agent tests")
    await test_agent()
    logger.info("Tests completed successfully")


if __name__ == "__main__":
    logger.info("Starting agent test application")
    asyncio.run(main())
