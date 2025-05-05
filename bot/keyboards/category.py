# Bot/keyboards/category.py
from aiogram.types import InlineKeyboardMarkup

from bot.api_client import ApiClient
from bot.keyboards.utils import build_inline_keyboard, ChooseSectionCallback, ChooseCategoryCallback, \
    ChooseSubCategoryCallback


async def create_section_keyboard(api_client: ApiClient) -> InlineKeyboardMarkup:
    sections = await api_client.get_sections()
    items = [(section.name, section.code, ChooseSectionCallback(section_code=section.code, back=False)) for section in
             sections]
    return build_inline_keyboard(items, adjust=1, back_button=True,
                                 back_callback=ChooseSectionCallback(section_code="back", back=True))


async def create_category_keyboard(api_client: ApiClient, section_code: str) -> InlineKeyboardMarkup:
    categories = await api_client.get_categories(section_code)
    items = [(category.name, category.code, ChooseCategoryCallback(category_code=category.code, back=False)) for
             category in categories]
    return build_inline_keyboard(items, adjust=1, back_button=True,
                                 back_callback=ChooseCategoryCallback(category_code="back", back=True))


async def create_subcategory_keyboard(api_client: ApiClient, section_code: str,
                                      category_code: str) -> InlineKeyboardMarkup:
    subcategories = await api_client.get_subcategories(section_code, category_code)
    items = [
        (subcategory.name, subcategory.code, ChooseSubCategoryCallback(subcategory_code=subcategory.code, back=False))
        for subcategory in subcategories]
    return build_inline_keyboard(items, adjust=1, back_button=True,
                                 back_callback=ChooseSubCategoryCallback(subcategory_code="back", back=True))
