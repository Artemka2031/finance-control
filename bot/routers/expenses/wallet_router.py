from aiogram import Router, F, Bot, html
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup

from ..expenses.state_classes import Expense
from ...api_client import ApiClient
from ...keyboards.category import create_section_keyboard
from ...keyboards.utils import ChooseWalletCallback, ChooseCreditorCallback
from ...keyboards.wallet import create_wallet_keyboard
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages

logger = configure_logger("[WALLET]", "green")

# Маппинг кодов кошельков на русские названия
WALLET_NAMES = {
    "project": "Проект",
    "borrow": "Взять в долг",
    "repay": "Вернуть долг",
    "dividends": "Дивиденды"
}

def create_wallet_router(bot: Bot, api_client: ApiClient):
    wallet_router = Router()

    @wallet_router.callback_query(Expense.wallet, ChooseWalletCallback.filter())
    @track_messages
    async def choose_wallet(query: CallbackQuery, state: FSMContext, bot: Bot,
                            callback_data: ChooseWalletCallback) -> Message:
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        wallet = callback_data.wallet
        wallet_name = WALLET_NAMES.get(wallet, wallet)
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} выбрал кошелёк '{wallet_name}' (code={wallet}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        await state.update_data(wallet=wallet, wallet_name=wallet_name)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, chat_id)

        # Редактируем сообщение бота
        try:
            await query.message.edit_text(f"Выбран кошелёк: 💸 {html.bold(wallet_name)}", reply_markup=None)
            logger.debug(f"Отредактировано сообщение {message_id} с кошельком '{wallet_name}' в чате {chat_id}")
            await state.update_data(wallet_message_id=message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id} в чате {chat_id}: {e}")
            # Отправляем новое сообщение
            new_message = await bot.send_message(
                chat_id=chat_id,
                text=f"Выбран кошелёк: 💸 {html.bold(wallet_name)}",
                reply_markup=None
            )
            await state.update_data(wallet_message_id=new_message.message_id)
            logger.debug(f"Отправлено новое сообщение {new_message.message_id} с кошельком '{wallet_name}'")

        # Отправляем новое сообщение в зависимости от кошелька
        if wallet in ["project", "dividends"]:
            section_message = await bot.send_message(
                chat_id=chat_id,
                text="Выберите раздел: 📋",
                reply_markup=await create_section_keyboard(api_client)
            )
            await state.update_data(status_message_id=section_message.message_id)
            await state.set_state(Expense.chapter_code)
            logger.info(f"Переход в состояние Expense.chapter_code, отправлено сообщение {section_message.message_id}")
        elif wallet == "borrow":
            creditors = await api_client.get_creditors()
            items = [(creditor.name, creditor.code, ChooseCreditorCallback(creditor=creditor.code, back=False)) for
                     creditor in creditors]
            back_callback = ChooseCreditorCallback(creditor="back", back=True)
            kb = api_client.build_inline_keyboard(items, adjust=1, back_button=True, back_callback=back_callback)

            creditor_message = await bot.send_message(
                chat_id=chat_id,
                text="Выберите кредитора: 👤",
                reply_markup=kb
            )
            await state.update_data(creditor_message_id=creditor_message.message_id)
            await state.set_state(Expense.creditor_borrow)
            logger.info(
                f"Переход в состояние Expense.creditor_borrow, отправлено сообщение {creditor_message.message_id}")
        elif wallet == "repay":
            creditors = await api_client.get_creditors()
            items = [(creditor.name, creditor.code, ChooseCreditorCallback(creditor=creditor.code, back=False)) for
                     creditor in creditors]
            back_callback = ChooseCreditorCallback(creditor="back", back=True)
            kb = api_client.build_inline_keyboard(items, adjust=1, back_button=True, back_callback=back_callback)

            creditor_message = await bot.send_message(
                chat_id=chat_id,
                text="Выберите кредитора для возврата долга: 👤",
                reply_markup=kb
            )
            await state.update_data(creditor_message_id=creditor_message.message_id)
            await state.set_state(Expense.creditor_return)
            logger.info(
                f"Переход в состояние Expense.creditor_return, отправлено сообщение {creditor_message.message_id}")

        return query.message  # Возвращаем отредактированное сообщение как ключевое

    @wallet_router.callback_query(ChooseCreditorCallback.filter(F.back == True))
    @track_messages
    async def back_to_wallet_selection(query: CallbackQuery, state: FSMContext, bot: Bot,
                                       callback_data: ChooseCreditorCallback) -> Message:
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

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, chat_id)

        # Создаём клавиатуру
        keyboard = create_wallet_keyboard()
        if not keyboard or not keyboard.inline_keyboard:
            logger.error(f"Клавиатура create_wallet_keyboard() пуста или None в чате {chat_id}")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        # Пробуем отредактировать сообщение
        try:
            await query.message.edit_text("Выберите кошелёк: 💸", reply_markup=keyboard)
            logger.debug(f"Отредактировано сообщение {message_id} для возврата к выбору кошелька в чате {chat_id}")
            await state.update_data(wallet_message_id=message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id} в чате {chat_id}: {e}")
            # Отправляем новое сообщение
            new_message = await bot.send_message(
                chat_id=chat_id,
                text="Выберите кошелёк: 💸",
                reply_markup=keyboard
            )
            logger.info(f"Отправлено новое сообщение {new_message.message_id} для выбора кошелька в чате {chat_id}")
            await state.update_data(wallet_message_id=new_message.message_id)
            return new_message

        await state.set_state(Expense.wallet)
        logger.info(f"Переход в состояние Expense.wallet, messages_to_delete={messages_to_delete}")
        return query.message

    @wallet_router.callback_query(Expense.creditor_borrow, ChooseCreditorCallback.filter(F.back == False))
    @track_messages
    async def choose_creditor(query: CallbackQuery, state: FSMContext, bot: Bot,
                              callback_data: ChooseCreditorCallback) -> Message:
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        creditor = callback_data.creditor
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(f"Пользователь {user_id} выбрал кредитора '{creditor}' (callback_data={callback_data}), "
                    f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        await state.update_data(creditor=creditor, creditor_name=creditor)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, chat_id)

        # Редактируем сообщение бота
        try:
            await query.message.edit_text(f"Выбран кредитор: 👤 {html.bold(creditor)}", reply_markup=None)
            logger.debug(f"Отредактировано сообщение {message_id} с кредитором '{creditor}' в чате {chat_id}")
            await state.update_data(creditor_message_id=message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id} в чате {chat_id}: {e}")
            # Отправляем новое сообщение
            new_message = await bot.send_message(
                chat_id=chat_id,
                text=f"Выбран кредитор: 👤 {html.bold(creditor)}",
                reply_markup=None
            )
            await state.update_data(creditor_message_id=new_message.message_id)
            logger.debug(f"Отправлено новое сообщение {new_message.message_id} с кредитором '{creditor}'")

        section_message = await bot.send_message(
            chat_id=chat_id,
            text="Выберите раздел: 📋",
            reply_markup=await create_section_keyboard(api_client)
        )
        await state.update_data(status_message_id=section_message.message_id)
        await state.set_state(Expense.chapter_code)
        logger.info(f"Переход в состояние Expense.chapter_code, отправлено сообщение {section_message.message_id}")
        return query.message

    @wallet_router.callback_query(Expense.creditor_return, ChooseCreditorCallback.filter(F.back == False))
    @track_messages
    async def choose_creditor_for_return_debt(query: CallbackQuery, state: FSMContext, bot: Bot,
                                              callback_data: ChooseCreditorCallback) -> Message:
        if not query.message:
            logger.warning(
                f"Нет сообщения в CallbackQuery от пользователя {query.from_user.id}, callback_data={callback_data}")
            return None
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        creditor = callback_data.creditor
        current_state = await state.get_state()
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])

        logger.info(
            f"Пользователь {user_id} выбрал кредитора для возврата долга '{creditor}' (callback_data={callback_data}), "
            f"message_id={message_id}, current_state={current_state}, messages_to_delete={messages_to_delete}")

        await state.update_data(creditor=creditor, creditor_name=creditor)

        # Удаляем временные сообщения
        await delete_tracked_messages(bot, state, chat_id)

        # Редактируем сообщение бота
        try:
            await query.message.edit_text(f"Возврат долга: 👤 {html.bold(creditor)}", reply_markup=None)
            logger.debug(f"Отредактировано сообщение {message_id} с возвратом долга для '{creditor}' в чате {chat_id}")
            await state.update_data(creditor_message_id=message_id)
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {message_id} в чате {chat_id}: {e}")
            # Отправляем новое сообщение
            new_message = await bot.send_message(
                chat_id=chat_id,
                text=f"Возврат долга: 👤 {html.bold(creditor)}",
                reply_markup=None
            )
            await state.update_data(creditor_message_id=new_message.message_id)
            logger.debug(f"Отправлено новое сообщение {new_message.message_id} с возвратом долга для '{creditor}'")

        amount_message = await bot.send_message(
            chat_id=chat_id,
            text="Введите сумму возврата: 💰"
        )
        await state.update_data(amount_message_id=amount_message.message_id)
        await state.set_state(Expense.amount)
        logger.info(f"Переход в состояние Expense.amount, отправлено сообщение {amount_message.message_id}")
        return query.message

    return wallet_router