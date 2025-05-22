import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.routers.expenses.expenses_router import create_expenses_router
from .comands import set_bot_commands
from .api_client import ApiClient
from .config import BOT_TOKEN
from .middleware.error_handling import ErrorHandlingMiddleware
from .middleware.logging import LoggingMiddleware
from .routers.ai_router import create_ai_router
from .routers.delete_router import create_delete_router
from .routers.income.income_router import create_income_router
from .routers.start_router import create_start_router
from .utils.logging import configure_logger

# Configure bot logger
logger = configure_logger("[BOT]", "green")

async def main():
    logger.info("Initializing bot and dispatcher")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    api_client = ApiClient()

    logger.debug("Registering middleware")
    dp.update.middleware(ErrorHandlingMiddleware())
    dp.update.middleware(LoggingMiddleware())

    logger.debug("Registering routers")
    dp.include_router(create_start_router(bot))
    dp.include_router(create_expenses_router(bot, api_client))
    dp.include_router(create_income_router(bot, api_client))
    dp.include_router(create_ai_router(bot, api_client))
    dp.include_router(create_delete_router(bot, api_client))


    try:
        logger.info("Bot is starting...")
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        logger.info("Bot is shutting down...")
        await api_client.close()
        await bot.session.close()

if __name__ == "__main__":
    logger.info("Starting bot application")
    asyncio.run(main())