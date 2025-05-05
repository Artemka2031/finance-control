# Bot/keyboards/utils.py
from typing import List, Tuple, Optional

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# Callback data classes
class ChooseWalletCallback(CallbackData, prefix="CWC"):
    wallet: str


class ChooseCreditorCallback(CallbackData, prefix="CCrC"):
    creditor: str
    back: bool


class DeleteOperationCallback(CallbackData, prefix="DelE"):
    operation_id: str
    delete: bool


class ConfirmDeleteOperationCallback(CallbackData, prefix="ConfDE"):
    operation_id: str
    confirm_delete: bool


class DeleteComingCallback(CallbackData, prefix="DelC"):
    operation_id: str
    delete: bool


class ConfirmDeleteComingCallback(CallbackData, prefix="ConfDC"):
    operation_id: str
    confirm_delete: bool


class TodayCallback(CallbackData, prefix="TDC"):
    today: str


class ChooseSectionCallback(CallbackData, prefix="CSecC"):
    section_code: str
    back: bool


class ChooseCategoryCallback(CallbackData, prefix="CCatC"):
    category_code: str
    back: bool


class ChooseSubCategoryCallback(CallbackData, prefix="CSubCatC"):
    subcategory_code: str
    back: bool


def build_inline_keyboard(
        items: List[Tuple[str, str, Optional[CallbackData]]],
        adjust: int = 1,
        back_button: bool = False,
        back_callback: Optional[CallbackData] = None
) -> InlineKeyboardMarkup:
    """
    Generic function to build inline keyboards.

    Args:
        items: List of tuples (text, identifier, callback_data).
        adjust: Number of buttons per row.
        back_button: Whether to add a back button.
        back_callback: Callback data for the back button.

    Returns:
        InlineKeyboardMarkup: The constructed keyboard.
    """
    builder = InlineKeyboardBuilder()

    for text, identifier, callback in items:
        if callback:
            builder.add(InlineKeyboardButton(text=text, callback_data=callback.pack()))

    if back_button and back_callback:
        builder.add(InlineKeyboardButton(text="<< Назад", callback_data=back_callback.pack()))

    builder.adjust(adjust)
    return builder.as_markup()
