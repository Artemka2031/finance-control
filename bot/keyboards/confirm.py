from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .utils import ConfirmOperationCallback


def create_confirm_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Подтвердить ✅",
                callback_data=ConfirmOperationCallback(confirm=True).pack()
            ),
            InlineKeyboardButton(
                text="Отменить 🚫",
                callback_data=ConfirmOperationCallback(confirm=False).pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
