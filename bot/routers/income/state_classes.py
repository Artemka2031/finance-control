# Bot/routers/income/state_classes.py
from aiogram.fsm.state import State, StatesGroup

class Income(StatesGroup):
    extra_messages = State()
    date_message_id = State()
    date = State()
    category_message_id = State()
    chapter_code = State()
    category_code = State()
    amount_message_id = State()
    amount = State()
    comment_message_id = State()
    comment = State()
    delete_income = State()