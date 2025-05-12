from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.filters.callback_data import CallbackData
from ..routers.expenses.state_classes import Expense
from ..utils.message_utils import format_operation_message
from ..keyboards.confirm import create_confirm_keyboard
from ..keyboards.utils import ChooseSectionCallback, ChooseCategoryCallback, ChooseSubCategoryCallback, \
    ChooseCreditorCallback
from ..api_client import ApiClient
from .agent import run_agent
from .utils import configure_logger

logger = configure_logger("[AGENT_ROUTER]", "yellow")


def create_agent_router(bot: Bot, api_client: ApiClient):
    router = Router()

    @router.message(Expense.ai_agent)
    async def handle_ai_agent(message: Message, state: FSMContext, bot: Bot):
        logger.info(f"Processing AI agent message: {message.text}")
        try:
            result = await run_agent(message.text)
            for msg in result.get("messages", []):
                reply_kwargs = {"text": msg["text"]}
                if msg.get("keyboard"):
                    reply_kwargs["reply_markup"] = msg["keyboard"]
                await message.answer(**reply_kwargs)

            for out in result.get("output", []):
                entities = out["entities"]
                state_data = {
                    "date": entities.get("date"),
                    "wallet": entities.get("wallet"),
                    "chapter_code": entities.get("chapter_code"),
                    "category_code": entities.get("category_code"),
                    "subcategory_code": entities.get("subcategory_code"),
                    "amount": entities.get("amount"),
                    "creditor": entities.get("creditor"),
                    "coefficient": entities.get("coefficient"),
                    "comment": entities.get("comment")
                }
                await state.update_data(**state_data)
                await state.set_state(Expense.confirm)
                operation_info = await format_operation_message(state_data, api_client)
                await message.answer(
                    f"Подтвердите операцию:\n{operation_info}",
                    reply_markup=create_confirm_keyboard()
                )
        except Exception as e:
            logger.error(f"Error in AI agent: {e}")
            await message.answer("Не удалось обработать запрос, попробуйте снова.")

    @router.callback_query(ChooseSectionCallback.filter())
    async def handle_section_choice(query: CallbackQuery, callback_data: ChooseSectionCallback, state: FSMContext):
        logger.debug(f"Selected section: {callback_data.section_code}")
        await state.update_data(chapter_code=callback_data.section_code)
        categories = await api_client.get_categories(callback_data.section_code)
        items = [(cat.name, cat.code, ChooseCategoryCallback(category_code=cat.code, back=False)) for cat in categories]
        keyboard = api_client.build_inline_keyboard(items, adjust=2)
        await query.message.edit_text("Выберите категорию:", reply_markup=keyboard)

    @router.callback_query(ChooseCategoryCallback.filter())
    async def handle_category_choice(query: CallbackQuery, callback_data: ChooseCategoryCallback, state: FSMContext):
        logger.debug(f"Selected category: {callback_data.category_code}")
        await state.update_data(category_code=callback_data.category_code)
        data = await state.get_data()
        subcategories = await api_client.get_subcategories(data["chapter_code"], callback_data.category_code)
        items = [(sub.name, sub.code, ChooseSubCategoryCallback(subcategory_code=sub.code, back=False)) for sub in
                 subcategories]
        keyboard = api_client.build_inline_keyboard(items, adjust=2)
        await query.message.edit_text("Выберите подкатегорию:", reply_markup=keyboard)

    @router.callback_query(ChooseSubCategoryCallback.filter())
    async def handle_subcategory_choice(query: CallbackQuery, callback_data: ChooseSubCategoryCallback,
                                        state: FSMContext):
        logger.debug(f"Selected subcategory: {callback_data.subcategory_code}")
        await state.update_data(subcategory_code=callback_data.subcategory_code)
        data = await state.get_data()
        operation_info = await format_operation_message(data, api_client)
        await state.set_state(Expense.confirm)
        await query.message.edit_text(
            f"Подтвердите операцию:\n{operation_info}",
            reply_markup=create_confirm_keyboard()
        )

    @router.callback_query(ChooseCreditorCallback.filter())
    async def handle_creditor_choice(query: CallbackQuery, callback_data: ChooseCreditorCallback, state: FSMContext):
        logger.debug(f"Selected creditor: {callback_data.creditor}")
        await state.update_data(creditor=callback_data.creditor)
        data = await state.get_data()
        operation_info = await format_operation_message(data, api_client)
        await state.set_state(Expense.confirm)
        await query.message.edit_text(
            f"Подтвердите операцию:\n{operation_info}",
            reply_markup=create_confirm_keyboard()
        )

    return router
