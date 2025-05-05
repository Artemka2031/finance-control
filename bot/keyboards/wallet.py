# Bot/keyboards/wallet.py
from aiogram.types import InlineKeyboardMarkup
from bot.keyboards.utils import build_inline_keyboard, ChooseWalletCallback

def create_wallet_keyboard() -> InlineKeyboardMarkup:
    wallets = [
        ("Проект", "project", ChooseWalletCallback(wallet="project")),
        ("Взять в долг", "borrow", ChooseWalletCallback(wallet="borrow")),
        ("Вернуть долг", "repay", ChooseWalletCallback(wallet="repay")),
        ("Дивиденды", "dividends", ChooseWalletCallback(wallet="dividends"))
    ]
    return build_inline_keyboard(wallets, adjust=2)