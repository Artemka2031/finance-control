from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from api_client import ApiClient

class ChooseIncomeCategoryCallback(CallbackData, prefix="income_cat"):
    category_code: str
    back: bool = False

async def create_income_category_keyboard(api_client: ApiClient) -> InlineKeyboardMarkup:
    categories = await api_client.get_incomes()
    keyboard = []
    for category in categories:
        keyboard.append([InlineKeyboardButton(
            text=category.name,
            callback_data=ChooseIncomeCategoryCallback(category_code=category.code).pack()
        )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)