from aiogram import Router, F, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup

from ..expenses.state_classes import Expense
from ...api_client import ApiClient
from ...keyboards.category import create_section_keyboard, create_category_keyboard, create_subcategory_keyboard
from ...keyboards.utils import ChooseSectionCallback, ChooseCategoryCallback, ChooseSubCategoryCallback
from ...keyboards.wallet import create_wallet_keyboard
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages

logger = configure_logger("[CATEGORY]", "purple")

def create_category_router(bot: Bot, api_client: ApiClient):
    category_router = Router()

    async def update_status_message(chat_id: int, state: FSMContext, bot: Bot, message_id: int = None,
                                    keyboard: InlineKeyboardMarkup = None) -> None:
        """Обновляет или создаёт статусное сообщение с текущими выборами раздела, категории и подкатегории."""
        data = await state.get_data()
        status_message_id = data.get("status_message_id")
        chapter_name = data.get("chapter_name", "Не выбрано")
        category_name = data.get("category_name", "Не выбрано")
        subcategory_name = data.get("subcategory_name", "Не выбрано")

        text = (
            f"Раздел: {html.bold(chapter_name)}\n"
            f"Категория: {html.bold(category_name)}\n"
            f"Подкатегория: {html.bold(subcategory_name)}"
        )

        try:
            if message_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                if message_id != status_message_id:
                    await state.update_data(status_message_id=message_id)
                logger.debug(f"Создано/обновлено статусное сообщение {message_id} в чате {chat_id}")
            else:
                new_message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                await state.update_data(status_message_id=new_message.message_id)
                logger.debug(f"Создано новое статусное сообщение {new_message.message_id} в чате {chat_id}")
        except Exception as e:
            logger.warning(f"Не удалось обновить статусное сообщение в чате {chat_id}: {e}")
            new_message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.update_data(status_message_id=new_message.message_id)
            logger.debug(f"Создано новое статусное сообщение {new_message.message_id} в чате {chat_id}")

    @category_router.callback_query(Expense.chapter_code, ChooseSectionCallback.filter(F.back == False))
    @track_messages
    async def set_chapter(query: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> Message:
        callback_data = kwargs.get("callback_data")
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        chapter_code = callback_data.section_code
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} выбрал раздел '{chapter_code}' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        # Получаем название раздела
        sections = await api_client.get_sections()
        chapter_name = next((sec.name for sec in sections if sec.code == chapter_code), chapter_code)
        await state.update_data(chapter_code=chapter_code, chapter_name=chapter_name)

        # Создаём клавиатуру категорий
        keyboard = await create_category_keyboard(api_client, chapter_code)

        # Обновляем статусное сообщение с клавиатурой категорий
        await update_status_message(chat_id, state, bot, message_id, keyboard)
        await state.set_state(Expense.category_code)
        logger.info(f"Переход в состояние Expense.category_code, обновлено сообщение {message_id}")
        return query.message

    @category_router.callback_query(Expense.chapter_code, ChooseSectionCallback.filter(F.back == True))
    @track_messages
    async def back_to_wallet(query: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> Message:
        callback_data = kwargs.get("callback_data")
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} нажал 'Назад' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        # Очищаем данные о разделе, категории и подкатегории
        await state.update_data(chapter_code=None, chapter_name="Не выбрано",
                                category_code=None, category_name="Не выбрано",
                                subcategory_code=None, subcategory_name="Не выбрано")

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, chat_id)

        # Создаём клавиатуру кошельков
        keyboard = create_wallet_keyboard()
        if not keyboard or not keyboard.inline_keyboard:
            logger.error(f"Клавиатура create_wallet_keyboard() пуста или None в чате {chat_id}")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        # Отправляем сообщение с клавиатурой кошельков
        try:
            await query.message.edit_text("Выберите кошелёк: 💸", reply_markup=keyboard)
            logger.debug(f"Отредактировано сообщение {message_id} для возврата к выбору кошелька в чате {chat_id}")
            await state.update_data(wallet_message_id=message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id} в чате {chat_id}: {e}")
            wallet_message = await bot.send_message(
                chat_id=chat_id,
                text="Выберите кошелёк: 💸",
                reply_markup=keyboard
            )
            await state.update_data(wallet_message_id=wallet_message.message_id)
            logger.info(f"Отправлено новое сообщение {wallet_message.message_id} для выбора кошелька в чате {chat_id}")
            return wallet_message

        await state.set_state(Expense.wallet)
        logger.info(f"Переход в состояние Expense.wallet, messages_to_delete={messages_to_delete}")
        return query.message

    @category_router.callback_query(Expense.category_code, ChooseCategoryCallback.filter(F.back == True))
    @track_messages
    async def back_to_chapters(query: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> Message:
        callback_data = kwargs.get("callback_data")
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} нажал 'Назад' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        # Очищаем данные о категории и подкатегории
        await state.update_data(category_code=None, category_name="Не выбрано",
                                subcategory_code=None, subcategory_name="Не выбрано")

        # Создаём клавиатуру разделов
        keyboard = await create_section_keyboard(api_client)

        # Обновляем статусное сообщение с клавиатурой разделов
        await update_status_message(chat_id, state, bot, message_id, keyboard)
        await state.set_state(Expense.chapter_code)
        logger.info(f"Переход в состояние Expense.chapter_code, обновлено сообщение {message_id}")
        return query.message

    @category_router.callback_query(Expense.category_code, ChooseCategoryCallback.filter(F.back == False))
    @track_messages
    async def set_category(query: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> Message:
        callback_data = kwargs.get("callback_data")
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        chapter_code = (await state.get_data())["chapter_code"]
        category_code = callback_data.category_code
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} выбрал категорию '{category_code}' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        # Получаем название категории
        categories = await api_client.get_categories(chapter_code)
        category_name = next((cat.name for cat in categories if cat.code == category_code), category_code)
        await state.update_data(category_code=category_code, category_name=category_name)

        # Проверяем наличие подкатегорий
        subcategories = await api_client.get_subcategories(chapter_code, category_code)
        if subcategories:
            keyboard = await create_subcategory_keyboard(api_client, chapter_code, category_code)
            await update_status_message(chat_id, state, bot, message_id, keyboard)
            await state.set_state(Expense.subcategory_code)
            logger.info(f"Переход в состояние Expense.subcategory_code, обновлено сообщение {message_id}")
            return query.message
        else:
            # Обновляем статусное сообщение без клавиатуры
            await update_status_message(chat_id, state, bot, message_id)
            # Отправляем сообщение для ввода суммы
            amount_message = await bot.send_message(
                chat_id=chat_id,
                text="Введите сумму расхода: 💰"
            )
            await state.update_data(amount_message_id=amount_message.message_id)
            await state.set_state(Expense.amount)
            logger.info(f"Переход в состояние Expense.amount, отправлено сообщение {amount_message.message_id}")
            return query.message

    @category_router.callback_query(Expense.subcategory_code, ChooseSubCategoryCallback.filter(F.back == True))
    @track_messages
    async def back_to_category(query: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> Message:
        callback_data = kwargs.get("callback_data")
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        chapter_code = (await state.get_data())["chapter_code"]
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} нажал 'Назад' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        # Очищаем данные о подкатегории
        await state.update_data(subcategory_code=None, subcategory_name="Не выбрано")

        # Создаём клавиатуру категорий
        keyboard = await create_category_keyboard(api_client, chapter_code)

        # Обновляем статусное сообщение с клавиатурой категорий
        await update_status_message(chat_id, state, bot, message_id, keyboard)
        await state.set_state(Expense.category_code)
        logger.info(f"Переход в состояние Expense.category_code, обновлено сообщение {message_id}")
        return query.message

    @category_router.callback_query(Expense.subcategory_code, ChooseSubCategoryCallback.filter(F.back == False))
    @track_messages
    async def set_subcategory(query: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> Message:
        callback_data = kwargs.get("callback_data")
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        chapter_code = (await state.get_data())["chapter_code"]
        category_code = (await state.get_data())["category_code"]
        subcategory_code = callback_data.subcategory_code
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} выбрал подкатегорию '{subcategory_code}' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        # Получаем название подкатегории
        subcategories = await api_client.get_subcategories(chapter_code, category_code)
        subcategory_name = next((sub.name for sub in subcategories if sub.code == subcategory_code), subcategory_code)
        await state.update_data(subcategory_code=subcategory_code, subcategory_name=subcategory_name)

        # Обновляем статусное сообщение без клавиатуры
        await update_status_message(chat_id, state, bot, message_id)

        # Отправляем сообщение для ввода суммы
        amount_message = await bot.send_message(
            chat_id=chat_id,
            text="Введите сумму расхода: 💰"
        )
        await state.update_data(amount_message_id=amount_message.message_id)
        await state.set_state(Expense.amount)
        logger.info(f"Переход в состояние Expense.amount, отправлено сообщение {amount_message.message_id}")
        return query.message

    return category_router