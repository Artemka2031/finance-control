import asyncio
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from api_client import ApiClient
from comands import set_bot_commands
from middleware.dependency_injection import DependencyInjectionMiddleware
from middleware.error_handling import ErrorHandlingMiddleware
from middleware.logging import LoggingMiddleware
from routers.ai_router import create_ai_router
from routers.delete_router import create_delete_router
from routers.expenses.expenses_router import create_expenses_router
from routers.income.income_router import create_income_router
from routers.start_router import create_start_router
from utils.logging import configure_logger

# ← ВСЁ про переменные окружения и .env.dev.dev теперь здесь
from config import BOT_TOKEN, BACKEND_URL, REDIS_URL, USE_REDIS

# --------------------------------------------------
logger = configure_logger("[BOT]", "green")
BASE_DIR = Path(__file__).resolve().parent  # bot/
logger.info(f"BASE_DIR: {BASE_DIR}")

bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def main() -> None:
    bot_info = await bot.get_me()
    bot_name = bot_info.username
    logger.info(f"Starting bot application for @{bot_name}")
    logger.info(f"Using gateway at: {BACKEND_URL}")

    # Storage: Redis → Memory fallback
    if USE_REDIS:
        logger.info(f"Using RedisStorage with REDIS_URL: {REDIS_URL}")
        try:
            storage = RedisStorage.from_url(REDIS_URL)
            await storage.redis.ping()
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}. Falling back to MemoryStorage.")
            storage = MemoryStorage()
    else:
        logger.info("Using MemoryStorage (Redis disabled)")
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)
    api_client = ApiClient(base_url=BACKEND_URL)

    # Middlewares
    dp.update.outer_middleware(DependencyInjectionMiddleware(bot=bot, api_client=api_client))
    dp.update.outer_middleware(ErrorHandlingMiddleware())
    dp.update.outer_middleware(LoggingMiddleware())

    # Routers
    dp.include_router(create_start_router(bot))
    dp.include_router(create_expenses_router(bot, api_client))
    dp.include_router(create_income_router(bot, api_client))
    dp.include_router(create_ai_router(bot, api_client))
    dp.include_router(create_delete_router(bot, api_client))

    try:
        logger.info(f"Bot @{bot_name} is starting…")
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        logger.info(f"Bot @{bot_name} is shutting down…")
        await api_client.close()
        await bot.session.close()
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
