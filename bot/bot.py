import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv

from bot.api_client import ApiClient
from bot.comands import set_bot_commands
from bot.middleware.dependency_injection import DependencyInjectionMiddleware
from bot.middleware.error_handling import ErrorHandlingMiddleware
from bot.middleware.logging import LoggingMiddleware
from bot.routers.ai_router.callback_handler import create_callback_router
from bot.routers.ai_router.message_handler import create_message_router
from bot.routers.delete_router import create_delete_router
from bot.routers.expenses.expenses_router import create_expenses_router
from bot.routers.income.income_router import create_income_router
from bot.routers.start_router import create_start_router
from bot.utils.logging import configure_logger

# Настройка логгера
logger = configure_logger("[BOT]", "green")

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env file")
if not BACKEND_URL:
    raise ValueError("BACKEND_URL is not set in .env file")

async def main():
    logger.info("Starting bot application")

    # Инициализация бота и диспетчера
    logger.info("Initializing bot and dispatcher")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = RedisStorage.from_url(REDIS_URL) if REDIS_URL else MemoryStorage()
    dp = Dispatcher(storage=storage)
    api_client = ApiClient(base_url=BACKEND_URL)

    # Регистрация middleware
    logger.debug("Registering middleware")
    dp.update.outer_middleware(DependencyInjectionMiddleware(bot=bot, api_client=api_client))
    dp.update.outer_middleware(ErrorHandlingMiddleware())
    dp.update.outer_middleware(LoggingMiddleware())

    # Регистрация роутеров
    logger.debug("Registering routers")
    dp.include_router(create_start_router(bot))
    dp.include_router(create_expenses_router(bot, api_client))
    dp.include_router(create_income_router(bot, api_client))
    dp.include_router(create_message_router(bot, api_client))
    dp.include_router(create_callback_router(bot, api_client))
    dp.include_router(create_delete_router(bot, api_client))

    try:
        logger.info("Bot is starting...")
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        logger.info("Bot is shutting down...")
        await api_client.close()
        await bot.session.close()
        await storage.close()

if __name__ == "__main__":
    asyncio.run(main())