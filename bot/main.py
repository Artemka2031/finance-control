# bot/main.py
from dotenv import load_dotenv
load_dotenv()

import asyncio, os
from loguru import logger

from aiogram import Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.bot import Bot, DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.storage.base import DefaultKeyBuilder

from bot.clients.gateway_client import GatewayClient

# Конфиг
BOT_TOKEN    = os.getenv('BOT_TOKEN_MAIN')
REDIS_URL    = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
GATEWAY_URL  = os.getenv('GATEWAY_URL', 'http://localhost:8000/v1')

# Логи в JSON
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO", serialize=True)

async def main():
    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(token=BOT_TOKEN, default=default_props)

    key_builder = DefaultKeyBuilder(prefix="fsm")
    storage = RedisStorage.from_url(REDIS_URL, key_builder=key_builder)
    dp = Dispatcher(storage=storage)

    dp['gateway'] = GatewayClient()

    logger.info("🤖 Bot starting…")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
