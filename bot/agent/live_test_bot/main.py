# Bot/agent/live_test_bot/main.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from ..config import BOT_TOKEN
from ..utils import setup_logging
from ...api_client import ApiClient
from .ai_router import create_ai_router

# Configure logger
logger = setup_logging()

async def main():
    logger.info("Initializing test bot for AI agent")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    api_client = ApiClient()

    # Register AI router
    logger.debug("Registering AI router")
    dp.include_router(create_ai_router(bot, api_client))

    # Start polling
    try:
        logger.info("Test bot is starting...")
        await dp.start_polling(bot)
    finally:
        logger.info("Test bot is shutting down...")
        await api_client.close()
        await bot.session.close()

if __name__ == "__main__":
    logger.info("Starting test bot application")
    asyncio.run(main())