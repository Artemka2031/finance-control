# Bot/routers/expenses/category_router.py
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.category import create_section_keyboard, create_category_keyboard, create_subcategory_keyboard
from bot.keyboards.utils import ChooseSectionCallback, ChooseCategoryCallback, ChooseSubCategoryCallback
from bot.keyboards.wallet import create_wallet_keyboard
from bot.routers.expenses.state_classes import Expense
from bot.utils.message_utils import delete_messages_after, track_message


def create_category_router(bot: Bot, api_client: ApiClient):
    category_router = Router()

    @category_router.callback_query(Expense.chapter_code, ChooseSectionCallback.filter(F.back == False))
    @delete_messages_after
    @track_message
    async def set_chapter(query: CallbackQuery, callback_data: ChooseSectionCallback, state: FSMContext) -> Message:
        chapter_code = callback_data.section_code
        await state.update_data(chapter_code=chapter_code)

        category_message = await query.message.answer(
            text=f"Выбран раздел. Выберите категорию:",
            reply_markup=await create_category_keyboard(api_client, chapter_code)
        )
        await state.set_state(Expense.category_code)
        return category_message

    @category_router.callback_query(Expense.chapter_code, ChooseSectionCallback.filter(F.back == True))
    @delete_messages_after
    @track_message
    async def back_to_wallet(query: CallbackQuery, state: FSMContext) -> Message:
        wallet_message = await query.message.answer(
            text="Выберите кошелек:",
            reply_markup=create_wallet_keyboard()
        )
        await state.set_state(Expense.wallet)
        return wallet_message

    @category_router.callback_query(Expense.category_code, ChooseCategoryCallback.filter(F.back == True))
    @delete_messages_after
    @track_message
    async def back_to_chapters(query: CallbackQuery, state: FSMContext) -> Message:
        chapter_message = await query.message.answer(
            text="Выберите раздел:",
            reply_markup=await create_section_keyboard(api_client)
        )
        await state.set_state(Expense.chapter_code)
        return chapter_message

    @category_router.callback_query(Expense.category_code, ChooseCategoryCallback.filter(F.back == False))
    @delete_messages_after
    @track_message
    async def set_category(query: CallbackQuery, callback_data: ChooseCategoryCallback, state: FSMContext) -> Message:
        chapter_code = (await state.get_data())["chapter_code"]
        category_code = callback_data.category_code
        await state.update_data(category_code=category_code)

        subcategories = await api_client.get_subcategories(chapter_code, category_code)
        if subcategories:
            subcategory_message = await query.message.answer(
                text=f"Выбрана категория. Выберите подкатегорию:",
                reply_markup=await create_subcategory_keyboard(api_client, chapter_code, category_code)
            )
            await state.set_state(Expense.subcategory_code)
            return subcategory_message
        else:
            amount_message = await query.message.answer(text="Введите сумму расхода:")
            await state.set_state(Expense.amount)
            return amount_message

    @category_router.callback_query(Expense.subcategory_code, ChooseSubCategoryCallback.filter(F.back == True))
    @delete_messages_after
    @track_message
    async def back_to_category(query: CallbackQuery, state: FSMContext) -> Message:
        chapter_code = (await state.get_data())["chapter_code"]
        category_message = await query.message.answer(
            text="Выберите категорию:",
            reply_markup=await create_category_keyboard(api_client, chapter_code)
        )
        await state.set_state(Expense.category_code)
        return category_message

    @category_router.callback_query(Expense.subcategory_code, ChooseSubCategoryCallback.filter(F.back == False))
    @delete_messages_after
    @track_message
    async def set_subcategory(query: CallbackQuery, callback_data: ChooseSubCategoryCallback,
                              state: FSMContext) -> Message:
        subcategory_code = callback_data.subcategory_code
        await state.update_data(subcategory_code=subcategory_code)

        amount_message = await query.message.answer(text="Введите сумму расхода:")
        await state.set_state(Expense.amount)
        return amount_message

    return category_router
