from aiogram.fsm.state import State, StatesGroup

class Income(StatesGroup):
    date = State()
    category_code = State()
    amount = State()
    comment = State()
    confirm = State()
    delete_income = State()