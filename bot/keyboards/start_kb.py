# Bot/keyboards/start_kb.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def create_start_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Расход ₽"))
    builder.add(KeyboardButton(text="Приход ₽"))
    builder.adjust(2)  # Two buttons per row
    return builder.as_markup(resize_keyboard=True)