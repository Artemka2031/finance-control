# Bot/routers/ai_router/states.py
from aiogram.fsm.state import State, StatesGroup


class MessageState(StatesGroup):
    initial = State()
    waiting_for_ai_input = State()
    waiting_for_clarification = State()
    confirming_operation = State()