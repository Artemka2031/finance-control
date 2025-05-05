# Bot/filters/check_date.py
import re
from datetime import datetime

from aiogram.filters import BaseFilter
from aiogram.types import Message


class CheckDateFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        # Patterns for DD.MM.YY and DD.MM.YYYY
        patterns = [r"^\d{2}\.\d{2}\.\d{2}$", r"^\d{2}\.\d{2}\.\d{4}$"]
        text = message.text

        # Check if the input matches any pattern
        if not any(re.match(pattern, text) for pattern in patterns):
            return False

        try:
            # Determine format based on length
            date_format = "%d.%m.%y" if len(text) == 8 else "%d.%m.%Y"
            datetime.strptime(text, date_format)
            return True
        except ValueError:
            return False
