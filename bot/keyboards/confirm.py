from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.keyboards.utils import ConfirmOperationCallback


def create_confirm_keyboard() -> InlineKeyboardMarkup:
    items = [
        ("Подтвердить", "confirm", ConfirmOperationCallback(confirm=True)),
        ("Отмена", "cancel", ConfirmOperationCallback(confirm=False))
    ]
    buttons = [[InlineKeyboardButton(text=text, callback_data=callback.pack()) for text, _, callback in items]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
