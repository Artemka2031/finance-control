import os
from openai import AsyncOpenAI
from ...utils.logging import configure_logger
from ...agent.config import OPENAI_API_KEY
logger = configure_logger("[TRANSCRIPTION]", "purple")

model_id = 'whisper-1'
language = "ru"

async def trancribe_audio(audio_file_path: str):
    async with AsyncOpenAI(api_key=OPENAI_API_KEY) as openai_client:
        with open(audio_file_path, 'rb') as audio_file:
            response = await openai_client.audio.transcriptions.create(
                model=model_id,
                file=audio_file,
                language='ru'
            )
            transcription_text = response.text
            audio_file.close()
        await openai_client.close()
    os.unlink(audio_file_path)
    return transcription_text