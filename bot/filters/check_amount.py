# Bot/filters/check_amount.py
from aiogram.filters import BaseFilter
from aiogram.types import Message


class CheckAmountFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        try:
            amount = float(message.text.replace(",", "."))
            return amount > 0
        except ValueError:
            return False
