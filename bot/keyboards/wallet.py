# Bot/keyboards/wallet.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from .utils import ChooseWalletCallback

def create_wallet_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора кошелька.
    """
    builder = InlineKeyboardBuilder()
    wallets = [
        ("Проект", "project"),
        ("Взять в долг", "borrow"),
        ("Вернуть долг", "repay"),
        ("Дивиденды", "dividends")
    ]
    for text, wallet in wallets:
        builder.add(InlineKeyboardButton(
            text=text,
            callback_data=ChooseWalletCallback(wallet=wallet).pack()
        ))
    builder.adjust(2)  # Две кнопки в ряду
    return builder.as_markup()