# bot/keyboards/utils.py
from typing import List, Tuple, Optional

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class TodayCallback(CallbackData, prefix="today"):
    today: str

class ChooseWalletCallback(CallbackData, prefix="CWC"):
    wallet: str


class ChooseSectionCallback(CallbackData, prefix="CSC"):
    section_code: str
    back: bool


class ChooseCategoryCallback(CallbackData, prefix="CC"):
    category_code: str
    back: bool


class ChooseSubCategoryCallback(CallbackData, prefix="CS"):
    subcategory_code: str
    back: bool


class ChooseCreditorCallback(CallbackData, prefix="CCR"):
    creditor: str
    back: bool


class DeleteOperationCallback(CallbackData, prefix="delete_op"):
    task_ids: str
    delete: bool

class ConfirmDeleteOperationCallback(CallbackData, prefix="confirm_delete_op"):
    task_ids: str
    confirm_delete: bool

class DeleteComingCallback(CallbackData, prefix="delete_coming"):
    task_ids: str
    delete: bool

class ConfirmDeleteComingCallback(CallbackData, prefix="confirm_delete_coming"):
    task_ids: str
    confirm_delete: bool

class ConfirmOperationCallback(CallbackData, prefix="confirm_op"):
    confirm: bool

def build_inline_keyboard(
        items: List[Tuple[str, str, CallbackData]],
        adjust: int = 1,
        back_button: bool = False,
        back_callback: Optional[CallbackData] = None
) -> InlineKeyboardMarkup:
    buttons = []
    for text, callback_id, callback in items:
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback.pack())])

    if back_button and back_callback:
        buttons.append([InlineKeyboardButton(text="Назад", callback_data=back_callback.pack())])

    # Adjust buttons per row if needed
    if adjust > 1:
        adjusted_buttons = []
        for i in range(0, len(buttons), adjust):
            adjusted_buttons.append([btn for row in buttons[i:i + adjust] for btn in row])
        buttons = adjusted_buttons

    return InlineKeyboardMarkup(inline_keyboard=buttons)
