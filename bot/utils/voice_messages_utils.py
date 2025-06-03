import os
from pathlib import Path

from bot.agent.agents.transcription import trancribe_audio
from bot.init_bot import bot

PATH_TO_AUDIO = f"{Path(f"{os.path.realpath(__file__)}").parent}/audios"

async def handle_audio_message(file_id: str, file_name: str):
    Path(PATH_TO_AUDIO).mkdir(parents=True, exist_ok=True)
    file = await bot.get_file(file_id)
    destination_path = f"{PATH_TO_AUDIO}/{file_name}"
    await bot.download_file(file_path=file.file_path, destination=destination_path)

    return await trancribe_audio(destination_path)

