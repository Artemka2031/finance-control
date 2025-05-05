# Bot/keyboards/delete.py
from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.utils import (
    build_inline_keyboard,
    DeleteOperationCallback,
    ConfirmDeleteOperationCallback,
    DeleteComingCallback,
    ConfirmDeleteComingCallback
)


def create_delete_operation_kb(operation_id: str, confirm: bool = False) -> InlineKeyboardMarkup:
    if not confirm:
        items = [(
            "Удалить",
            f"delete_{operation_id}",
            DeleteOperationCallback(operation_id=operation_id, delete=True)
        )]
        return build_inline_keyboard(items, adjust=1)
    else:
        items = [
            (
                "Удалить",
                f"confirm_delete_{operation_id}",
                ConfirmDeleteOperationCallback(operation_id=operation_id, confirm_delete=True)
            ),
            (
                "Отмена",
                f"cancel_delete_{operation_id}",
                ConfirmDeleteOperationCallback(operation_id=operation_id, confirm_delete=False)
            )
        ]
        return build_inline_keyboard(items, adjust=2)


def create_delete_coming_kb(operation_id: str, confirm: bool = False) -> InlineKeyboardMarkup:
    if not confirm:
        items = [(
            "Удалить",
            f"delete_coming_{operation_id}",
            DeleteComingCallback(operation_id=operation_id, delete=True)
        )]
        return build_inline_keyboard(items, adjust=1)
    else:
        items = [
            (
                "Удалить",
                f"confirm_delete_coming_{operation_id}",
                ConfirmDeleteComingCallback(operation_id=operation_id, confirm_delete=True)
            ),
            (
                "Отмена",
                f"cancel_delete_coming_{operation_id}",
                ConfirmDeleteComingCallback(operation_id=operation_id, confirm_delete=False)
            )
        ]
        return build_inline_keyboard(items, adjust=2)
