# Bot/routers/ai_router/states.py
from aiogram.fsm.state import StatesGroup, State


class MessageState(StatesGroup):
    waiting_for_ai_input = State()
    waiting_for_clarification = State()
    waiting_for_text_input = State()
    confirming_operation = State()  # Новое состояние