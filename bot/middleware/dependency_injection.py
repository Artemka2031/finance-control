# Bot/middleware/dependency_injection.py
from typing import Dict, Any, Callable, Awaitable

from aiogram import Bot, BaseMiddleware
from aiogram.types import TelegramObject

from api_client import ApiClient
from utils.logging import configure_logger

logger = configure_logger("[DI_MIDDLEWARE]", "green")


class DependencyInjectionMiddleware(BaseMiddleware):
    def __init__(self, bot: Bot, api_client: ApiClient):
        super().__init__()
        self.bot = bot
        self.api_client = api_client

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        # logger.debug("Entering DependencyInjectionMiddleware")
        data["bot"] = self.bot
        data["api_client"] = self.api_client
        try:
            result = await handler(event, data)
            # logger.debug("Handler completed in DependencyInjectionMiddleware")
            return result
        except Exception as e:
            logger.error(f"Handler failed in DependencyInjectionMiddleware: {e}")
            raise
