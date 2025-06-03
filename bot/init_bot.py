import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.config import BOT_TOKEN

load_dotenv()

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env file")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)