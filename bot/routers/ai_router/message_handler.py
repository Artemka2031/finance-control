# Bot/routers/ai_router/message_handler.py
import asyncio

from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Voice

from .agent_processor import process_agent_request, handle_agent_result
from .states import MessageState
from ...agent.agent import Agent
from ...api_client import ApiClient
from ...utils.logging import configure_logger
from ...utils.message_utils import track_messages, delete_tracked_messages

logger = configure_logger("[MESSAGE_HANDLER]", "yellow")


def create_message_router(bot: Bot, api_client: ApiClient) -> Router:
    message_router = Router()

    @message_router.message(F.text.startswith("#ИИ"))
    @track_messages
    async def message_handler(message: Message, state: FSMContext, bot: Bot, api_client: ApiClient) -> None:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.replace("#ИИ", "").strip()

        if not input_text:
            logger.warning(f"Пользователь {user_id} отправил пустое сообщение #ИИ")
            await bot.send_message(
                chat_id=chat_id,
                text="🤔 Укажите запрос после #ИИ, например: #ИИ Купил кофе за 250",
                parse_mode="HTML"
            )
            return

        logger.info(f"Пользователь {user_id} отправил запрос #ИИ: {input_text}")
        await delete_tracked_messages(bot, state, chat_id)
        await state.set_state(MessageState.waiting_for_ai_input)

        processing_message = await bot.send_message(
            chat_id=chat_id,
            text="🔄 Начинаем обработку...",
            parse_mode="HTML"
        )

        agent = Agent(bot=bot, chat_id=chat_id, message_id=processing_message.message_id)
        result = await process_agent_request(agent, input_text, interactive=True)
        await handle_agent_result(
            result, bot, state, chat_id, input_text, api_client, message_id=processing_message.message_id
        )
        return {"status": "processed"}


    @message_router.message(MessageState.waiting_for_ai_input, F.voice)
    @track_messages
    async def handle_voice_message(message: Voice, state: FSMContext, bot: Bot, api_client: ApiClient) -> None:
        user_id = message.from_user.id
        chat_id = message.chat.id

        logger.info(f"Пользователь {user_id} отправил голосовое сообщение")
        await delete_tracked_messages(bot, state, chat_id)
        await state.set_state(MessageState.waiting_for_clarification)

        # Имитация транскрипции через Whisper
        fake_transcription = "Купил кофе за 250 рублей"  # Заглушка
        logger.debug(f"Имитация транскрипции для пользователя {user_id}: {fake_transcription}")

        transcription_message = await bot.send_message(
            chat_id=chat_id,
            text=f"🎙️ Распознанный текст: {fake_transcription}",
            parse_mode="HTML"
        )
        await asyncio.sleep(1.0)  # Имитация задержки обработки

        processing_message = await bot.send_message(
            chat_id=chat_id,
            text="🔍 Обрабатываем голосовой запрос...",
            parse_mode="HTML"
        )

        agent = Agent(bot=bot, chat_id=chat_id, message_id=processing_message.message_id)
        result = await process_agent_request(agent, fake_transcription, interactive=True)
        await handle_agent_result(
            result, bot, state, chat_id, fake_transcription, api_client, message_id=processing_message.message_id
        )

    @message_router.message(MessageState.waiting_for_clarification, F.text)
    @track_messages
    async def handle_clarification_message(message: Message, state: FSMContext, bot: Bot,
                                           api_client: ApiClient) -> None:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.strip()
        data = await state.get_data()
        agent_state = data.get("agent_state")
        input_text_orig = data.get("input_text", "")

        if not agent_state or not agent_state.get("actions"):
            logger.debug(f"Нет активного состояния агента для пользователя {user_id}")
            await state.set_state(MessageState.waiting_for_ai_input)
            await bot.send_message(
                chat_id=chat_id,
                text="🤔 Пожалуйста, начните запрос с #ИИ",
                parse_mode="HTML"
            )
            return

        clarification_needed = False
        clarification_field = None
        request_index = None
        for action in agent_state["actions"]:
            if action["needs_clarification"]:
                clarification_field = action["clarification_field"]
                request_index = action["request_index"]
                clarification_needed = True
                break

        if not clarification_needed or not clarification_field:
            logger.debug(f"Нет необходимости в уточнении для пользователя {user_id}")
            await bot.send_message(
                chat_id=chat_id,
                text="🤔 Пожалуйста, уточните данные или начните новый запрос с #ИИ",
                parse_mode="HTML"
            )
            return

        if clarification_field not in ["amount", "date", "coefficient", "comment"]:
            logger.debug(f"Ожидается выбор через клавиатуру для поля {clarification_field}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"📋 Пожалуйста, выберите {clarification_field} через клавиатуру",
                parse_mode="HTML"
            )
            return

        logger.info(f"Пользователь {user_id} уточнил {clarification_field}: {input_text}")
        agent_state["requests"][request_index]["entities"][clarification_field] = input_text
        if clarification_field in agent_state["requests"][request_index]["missing"]:
            agent_state["requests"][request_index]["missing"].remove(clarification_field)
        agent_state["messages"].append({"role": "user", "content": f"Clarified: {clarification_field}={input_text}"})

        processing_message = await bot.send_message(
            chat_id=chat_id,
            text="🔍 Обрабатываем уточнение...",
            parse_mode="HTML"
        )

        agent = Agent(bot=bot, chat_id=chat_id, message_id=processing_message.message_id)
        result = await process_agent_request(agent, input_text_orig, interactive=True, prev_state=agent_state)
        await handle_agent_result(
            result, bot, state, chat_id, input_text_orig, api_client, message_id=processing_message.message_id
        )

    @message_router.message(MessageState.waiting_for_text_input, F.text)
    @track_messages
    async def handle_text_input(message: Message, state: FSMContext, bot: Bot, api_client: ApiClient) -> None:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.strip()
        data = await state.get_data()
        agent_state = data.get("agent_state")
        input_text_orig = data.get("input_text", "")
        request_index = data.get("request_index", 0)

        if not agent_state:
            logger.error(f"Нет предыдущего состояния для пользователя {user_id}")
            await bot.send_message(
                chat_id=chat_id,
                text="😓 Ошибка: состояние утеряно. Начните заново с #ИИ",
                parse_mode="HTML"
            )
            await state.set_state(MessageState.waiting_for_ai_input)
            return

        logger.info(f"Пользователь {user_id} ввёл текст: {input_text}")
        for req in agent_state["requests"]:
            if req["index"] == request_index:
                req["entities"]["subcategory_code"] = input_text
                if "subcategory_code" in req["missing"]:
                    req["missing"].remove("subcategory_code")
                break

        processing_message = await bot.send_message(
            chat_id=chat_id,
            text="🔍 Обрабатываем введённую подкатегорию...",
            parse_mode="HTML"
        )

        agent = Agent(bot=bot, chat_id=chat_id, message_id=processing_message.message_id)
        result = await process_agent_request(agent, input_text_orig, interactive=True, prev_state=agent_state)
        await handle_agent_result(
            result, bot, state, chat_id, input_text_orig, api_client, message_id=processing_message.message_id
        )

    return message_router