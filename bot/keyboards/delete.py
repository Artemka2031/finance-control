from aiogram.types import InlineKeyboardMarkup

from .utils import (
    build_inline_keyboard,
    DeleteOperationCallback,
    ConfirmDeleteOperationCallback,
    DeleteComingCallback,
    ConfirmDeleteComingCallback
)


def create_delete_operation_kb(task_ids: list[str], confirm: bool = False) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для удаления операции по списку task_ids.
    Если confirm=True, показывает кнопки 'Удалить' и 'Отмена'.
    """
    task_ids_str = ",".join(task_ids) if task_ids else "noop"
    if not confirm:
        items = [(
            "Удалить 🗑️",
            f"delete_{task_ids_str}",
            DeleteOperationCallback(task_ids=task_ids_str, delete=True)
        )]
        return build_inline_keyboard(items, adjust=1)
    else:
        items = [
            (
                "Удалить ✅",
                f"confirm_delete_{task_ids_str}",
                ConfirmDeleteOperationCallback(task_ids=task_ids_str, confirm_delete=True)
            ),
            (
                "Отмена 🚫",
                f"cancel_delete_{task_ids_str}",
                ConfirmDeleteOperationCallback(task_ids=task_ids_str, confirm_delete=False)
            )
        ]
        return build_inline_keyboard(items, adjust=2)


def create_delete_coming_kb(task_ids: list[str], confirm: bool = False) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для удаления входящей операции по списку task_ids.
    Если confirm=True, показывает кнопки 'Удалить' и 'Отмена'.
    """
    task_ids_str = ",".join(task_ids) if task_ids else "noop"
    if not confirm:
        items = [(
            "Удалить 🗑️",
            f"delete_coming_{task_ids_str}",
            DeleteComingCallback(task_ids=task_ids_str, delete=True)
        )]
        return build_inline_keyboard(items, adjust=1)
    else:
        items = [
            (
                "Удалить ✅",
                f"confirm_delete_coming_{task_ids_str}",
                ConfirmDeleteComingCallback(task_ids=task_ids_str, confirm_delete=True)
            ),
            (
                "Отмена 🚫",
                f"cancel_delete_coming_{task_ids_str}",
                ConfirmDeleteComingCallback(task_ids=task_ids_str, confirm_delete=False)
            )
        ]
        return build_inline_keyboard(items, adjust=2)