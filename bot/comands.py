from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

async def set_bot_commands(bot: Bot):
    """
    Регистрирует команды бота в меню Telegram.
    """
    commands = [
        BotCommand(command="/add_expense", description="Добавить расход"),
        BotCommand(command="/cancel_expense", description="Отменить добавление расхода"),
        BotCommand(command="/add_income", description="Добавить доход"),
        BotCommand(command="/cancel_income", description="Отменить добавление дохода"),
        BotCommand(command="/start_ai", description="Начать работу с ИИ"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())