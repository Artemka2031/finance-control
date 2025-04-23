# gateway/app/services/core/constants.py
from typing import Dict

# Шаблоны комментариев: начинаются с суммы для идентификации
COMMENT_TEMPLATES: Dict[str, str] = {
    "add_expense": "{amount} ₽: Расход добавлен: {comment}",
    "add_income": "{amount} ₽: Приход добавлен: {comment}",
    "record_borrowing": "{amount} ₽: Кредитные деньги взяты на: {comment}",
    "record_repayment": "{amount} ₽: Долг возвращён на: {comment}",
    "record_saving": "{amount} ₽: Экономия достигнута за счёт: {comment}",
}