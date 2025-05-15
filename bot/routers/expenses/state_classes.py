from aiogram.fsm.state import State, StatesGroup

class Expense(StatesGroup):
    date = State()
    wallet = State()
    chapter_code = State()
    category_code = State()
    subcategory_code = State()
    amount = State()

    coefficient = State()

    comment = State()
    creditor_borrow = State()
    creditor_return = State()
    delete_expense = State()
    confirm = State()
