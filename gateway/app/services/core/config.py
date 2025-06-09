import os
import json
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# ──────────────────────────────────────────────────────────────────────────────
#  Базовый путь (корень репозитория)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
logger.debug(f"BASE_DIR: {BASE_DIR}")

# ──────────────────────────────────────────────────────────────────────────────
#  Локальная разработка: .env.dev читаем только если он действительно есть
# ──────────────────────────────────────────────────────────────────────────────
ENV_FILE = BASE_DIR / ".env.dev"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
    logger.debug(".env.dev loaded")
else:
    logger.debug(".env.dev not found, skipping")

# ──────────────────────────────────────────────────────────────────────────────
#  Переменные окружения
# ──────────────────────────────────────────────────────────────────────────────
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
REDIS_URL       = os.getenv("REDIS_URL")
FASTAPI_PORT    = int(os.getenv("FASTAPI_PORT", "8000"))
DATABASE_PATH   = os.getenv("DATABASE_PATH", "tasks.db")

GS_MAX_ROWS     = int(os.getenv("GS_MAX_ROWS", "300"))
WORKSHEET_NAME  = os.getenv("WORKSHEET_NAME", "Общая таблица")
PROJECT_ID      = os.getenv("PROJECT_ID", "project1")

# ──────────────────────────────────────────────────────────────────────────────
#  GOOGLE_CREDENTIALS: переменная‑JSON или файл creds.json
# ──────────────────────────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_JSON: str | None = os.getenv("GOOGLE_CREDENTIALS")

def _load_creds_file(path: Path) -> str | None:
    if path.exists():
        logger.info(f"Reading GOOGLE_CREDENTIALS from file {path}")
        return path.read_text(encoding="utf-8")
    return None

if not GOOGLE_CREDENTIALS_JSON:
    creds_path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", BASE_DIR / "creds.json"))
    GOOGLE_CREDENTIALS_JSON = _load_creds_file(creds_path)

GOOGLE_CREDENTIALS: dict | None = None
if GOOGLE_CREDENTIALS_JSON:
    try:
        GOOGLE_CREDENTIALS = json.loads(GOOGLE_CREDENTIALS_JSON)
        logger.info("Successfully parsed GOOGLE_CREDENTIALS")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse GOOGLE_CREDENTIALS JSON: {e}")
        raise

# ──────────────────────────────────────────────────────────────────────────────
#  Проверка обязательных параметров
# ──────────────────────────────────────────────────────────────────────────────
_missing = [
    name for name, value in {
        "SPREADSHEET_URL"   : SPREADSHEET_URL,
        "GOOGLE_CREDENTIALS": GOOGLE_CREDENTIALS,
        "REDIS_URL"         : REDIS_URL,
    }.items() if not value
]
if _missing:
    logger.error(f"Обязательные переменные/секреты не заданы: {', '.join(_missing)}")
    raise EnvironmentError(f"Обязательные переменные/секреты не заданы: {', '.join(_missing)}")

# ──────────────────────────────────────────────────────────────────────────────
#  Настройка логирования
# ──────────────────────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    level="DEBUG",
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level:<8}</level> | "
        "<cyan>{name}:{function}:{line}</cyan> - "
        "<b>{message}</b>"
    ),
    colorize=True,
)
log = logger

log.info(
    f"Configuration loaded: "
    f"SPREADSHEET_URL={SPREADSHEET_URL}, "
    f"REDIS_URL={REDIS_URL}, "
    f"FASTAPI_PORT={FASTAPI_PORT}, "
    f"GS_MAX_ROWS={GS_MAX_ROWS}, "
    f"WORKSHEET_NAME={WORKSHEET_NAME}, "
    f"DATABASE_PATH={DATABASE_PATH}, "
    f"PROJECT_ID={PROJECT_ID}"
)
