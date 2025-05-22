from aiogram import Router, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Voice
from .states import MessageState
from .agent_processor import process_agent_request, handle_agent_result
from ...agent.agent import Agent
from ...api_client import ApiClient
from ...utils.message_utils import track_messages, delete_tracked_messages
from ...utils.logging import configure_logger

logger = configure_logger("[MESSAGE_HANDLER]", "yellow")


def create_message_router(bot: Bot, api_client: ApiClient) -> Router:
    message_router = Router()
    agent = Agent()

    @message_router.message(MessageState.waiting_for_ai_input, F.text.contains("#ИИ"))
    @track_messages
    async def handle_ai_message(message: Message, state: FSMContext, bot: Bot) -> Message:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.replace("#ИИ", "").strip()

        if not input_text:
            logger.warning(f"Пользователь {user_id} отправил пустое сообщение #ИИ")
            return await bot.send_message(
                chat_id=chat_id,
                text="🤔 Укажите запрос после #ИИ, например: #ИИ Купил кофе за 250",
                parse_mode="HTML"
            )

        logger.info(f"Пользователь {user_id} отправил запрос #ИИ: {input_text}")
        await delete_tracked_messages(bot, state, chat_id)
        await state.set_state(MessageState.waiting_for_clarification)

        processing_message = await bot.send_message(
            chat_id=chat_id,
            text="🔍 Начинаем обработку...",
            parse_mode="HTML"
        )

        result = await process_agent_request(agent, input_text, interactive=True)
        return await handle_agent_result(
            result, bot, state, chat_id, input_text, api_client,
            message_id=processing_message.message_id
        )

    @message_router.message(MessageState.waiting_for_ai_input, F.voice)
    @track_messages
    async def handle_voice_message(message: Voice, state: FSMContext, bot: Bot) -> Message:
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

        result = await process_agent_request(agent, fake_transcription, interactive=True)
        return await handle_agent_result(
            result, bot, state, chat_id, fake_transcription, api_client,
            message_id=processing_message.message_id
        )

    @message_router.message(MessageState.waiting_for_clarification, F.text)
    @track_messages
    async def handle_clarification_message(message: Message, state: FSMContext, bot: Bot) -> Message:
        user_id = message.from_user.id
        chat_id = message.chat.id
        input_text = message.text.strip()
        data = await state.get_data()
        agent_state = data.get("agent_state")
        input_text_orig = data.get("input_text", "")

        if not agent_state or not agent_state.get("actions"):
            logger.debug(f"Нет активного состояния агента для пользователя {user_id}")
            await state.set_state(MessageState.waiting_for_ai_input)
            return await bot.send_message(
                chat_id=chat_id,
                text="🤔 Пожалуйста, начните запрос с #ИИ",
                parse_mode="HTML"
            )

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
            return await bot.send_message(
                chat_id=chat_id,
                text="🤔 Пожалуйста, уточните данные или начните новый запрос с #ИИ",
                parse_mode="HTML"
            )

        if clarification_field not in ["amount", "date", "coefficient", "comment"]:
            logger.debug(f"Ожидается выбор через клавиатуру для поля {clarification_field}")
            return await bot.send_message(
                chat_id=chat_id,
                text=f"📋 Пожалуйста, выберите {clarification_field} через клавиатуру",
                parse_mode="HTML"
            )

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

        result = await process_agent_request(agent, input_text_orig, interactive=True, prev_state=agent_state)
        return await handle_agent_result(
            result, bot, state, chat_id, input_text_orig, api_client,
            message_id=processing_message.message_id
        )

    return message_router
