from pathlib import Path

from aiogram import Bot

from agent.agents.transcription import trancribe_audio
# Импортируем из централизованного конфига
from config import PATH_TO_AUDIO


async def handle_audio_message(bot: Bot, file_id: str, file_name: str):
    # Создаём папку для хранения (если её ещё нет)
    Path(PATH_TO_AUDIO).mkdir(parents=True, exist_ok=True)

    # Скачиваем файл и сохраняем по пути PATH_TO_AUDIO
    file = await bot.get_file(file_id)
    destination_path = f"{PATH_TO_AUDIO}/{file_name}"
    await bot.download_file(file_path=file.file_path, destination=destination_path)

    # Запускаем транскрипцию и возвращаем результат
    return await trancribe_audio(destination_path)
