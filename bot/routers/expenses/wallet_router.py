# Bot/routers/expenses/wallet_router.py
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..expenses.state_classes import Expense
from ...api_client import ApiClient
from ...keyboards.category import create_section_keyboard
from ...keyboards.utils import ChooseWalletCallback, ChooseCreditorCallback
from ...keyboards.wallet import create_wallet_keyboard
from ...utils.message_utils import delete_messages_after, track_message


def create_wallet_router(bot: Bot, api_client: ApiClient):
    wallet_router = Router()

    @wallet_router.callback_query(Expense.wallet, ChooseWalletCallback.filter())
    @delete_messages_after
    @track_message
    async def choose_wallet(query: CallbackQuery, callback_data: ChooseWalletCallback, state: FSMContext,
                            bot: Bot) -> Message:
        wallet = callback_data.wallet
        await state.update_data(wallet=wallet)
        await query.message.edit_text(f"Выбран кошелек: {wallet}", reply_markup=None)

        if wallet in ["project", "dividends"]:
            section_message = await bot.send_message(
                chat_id=query.message.chat.id,
                text="Выберите раздел:",
                reply_markup=await create_section_keyboard(api_client)
            )
            await state.set_state(Expense.chapter_code)
            return section_message
        elif wallet == "borrow":
            creditors = await api_client.get_creditors()
            items = [(creditor.name, creditor.code, ChooseCreditorCallback(creditor=creditor.code, back=False)) for
                     creditor in creditors]
            back_callback = ChooseCreditorCallback(creditor="back", back=True)
            kb = api_client.build_inline_keyboard(items, adjust=1, back_button=True, back_callback=back_callback)

            creditor_message = await bot.send_message(
                chat_id=query.message.chat.id,
                text="Выберите кредитора:",
                reply_markup=kb
            )
            await state.set_state(Expense.creditor_borrow)
            return creditor_message
        elif wallet == "repay":
            creditors = await api_client.get_creditors()
            items = [(creditor.name, creditor.code, ChooseCreditorCallback(creditor=creditor.code, back=False)) for
                     creditor in creditors]
            back_callback = ChooseCreditorCallback(creditor="back", back=True)
            kb = api_client.build_inline_keyboard(items, adjust=1, back_button=True, back_callback=back_callback)

            creditor_message = await bot.send_message(
                chat_id=query.message.chat.id,
                text="Выберите кредитора для возврата долга:",
                reply_markup=kb
            )
            await state.set_state(Expense.creditor_return)
            return creditor_message

    @wallet_router.callback_query(ChooseCreditorCallback.filter(F.back == True))
    @delete_messages_after
    @track_message
    async def back_to_wallet_selection(query: CallbackQuery, state: FSMContext, bot: Bot) -> Message:
        wallet_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text="Выберите кошелек:",
            reply_markup=create_wallet_keyboard()
        )
        await state.set_state(Expense.wallet)
        return wallet_message

    @wallet_router.callback_query(Expense.creditor_borrow, ChooseCreditorCallback.filter(F.back == False))
    @delete_messages_after
    @track_message
    async def choose_creditor(query: CallbackQuery, callback_data: ChooseCreditorCallback, state: FSMContext,
                              bot: Bot) -> Message:
        creditor = callback_data.creditor
        await state.update_data(creditor=creditor)
        await query.message.edit_text(f"Выбран кредитор: {creditor}", reply_markup=None)

        section_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text=f"Выбран кредитор: {creditor}. \nВыберите раздел:",
            reply_markup=await create_section_keyboard(api_client)
        )
        await state.set_state(Expense.chapter_code)
        return section_message

    @wallet_router.callback_query(Expense.creditor_return, ChooseCreditorCallback.filter(F.back == False))
    @delete_messages_after
    @track_message
    async def choose_creditor_for_return_debt(query: CallbackQuery, callback_data: ChooseCreditorCallback,
                                              state: FSMContext, bot: Bot) -> Message:
        creditor = callback_data.creditor
        await state.update_data(creditor=creditor)
        await query.message.edit_text(f"Возврат долга: {creditor}", reply_markup=None)

        amount_message = await bot.send_message(
            chat_id=query.message.chat.id,
            text="Введите сумму возврата:"
        )
        await state.set_state(Expense.amount)
        return amount_message

    return wallet_router