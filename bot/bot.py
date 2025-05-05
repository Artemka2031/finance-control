import asyncio
from aiogram import Bot, Dispatcher
from .config import BOT_TOKEN
from .api_client import ApiClient
from .commands import create_start_router
from .middleware.error_handling import ErrorHandlingMiddleware
from .middleware.logging import LoggingMiddleware
from .routers.expenses.expenses_router import create_expenses_router

async def main():
    # Initialize bot and dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    api_client = ApiClient()

    # Setup middleware
    dp.update.middleware(ErrorHandlingMiddleware())
    dp.update.middleware(LoggingMiddleware())

    # Register routers
    dp.include_router(create_start_router())
    dp.include_router(create_expenses_router(bot, api_client))

    # Start polling
    try:
        print("Bot is starting...")
        await dp.start_polling(bot)
    finally:
        print("Bot is shutting down...")
        await api_client.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())