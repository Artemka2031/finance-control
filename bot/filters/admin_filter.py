# Bot/filters/admin_filter.py
from aiogram.filters import BaseFilter
from aiogram.types import Message


class AdminFilter(BaseFilter):
    admin_ids = [123456789, 987654321]  # Замените на реальные ID администраторов

    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in self.admin_ids
