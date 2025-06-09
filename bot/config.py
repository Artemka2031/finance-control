import os
from pathlib import Path
from dotenv import load_dotenv

# Путь до корня проекта (папка, где лежит .env.dev)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env.dev")  # Загружаем .env.dev для разработки

# --- Обязательные переменные -------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")

# --- Переменные для обработки аудио ------------------------------------------
PATH_TO_AUDIO = os.getenv("PATH_TO_AUDIO")

# --- Дополнительные переменные ----------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # если нужна интеграция с OpenAI
REDIS_URL = os.getenv("REDIS_URL")
USE_REDIS = os.getenv("USE_REDIS", "true").lower() == "true"

# --- Базовые проверки --------------------------------------------------------
_missing = [
    name for name, value in {
        "BOT_TOKEN": BOT_TOKEN,
        "BACKEND_URL": BACKEND_URL,
        "PATH_TO_AUDIO": PATH_TO_AUDIO,
    }.items() if not value
]

if _missing:
    raise EnvironmentError(
        f"Не заданы обязательные переменные в .env.dev: {', '.join(_missing)}"
    )
