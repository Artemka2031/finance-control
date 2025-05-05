from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from .utils import TodayCallback
from datetime import timedelta

def create_today_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    today = datetime.now().strftime("%d.%m.%Y")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
    builder.add(InlineKeyboardButton(text="Сегодня", callback_data=TodayCallback(today=today).pack()))
    builder.add(InlineKeyboardButton(text="Вчера", callback_data=TodayCallback(today=yesterday).pack()))
    builder.adjust(1)
    return builder.as_markup()