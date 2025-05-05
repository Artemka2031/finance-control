# gateway/app/services/core/config.py
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Указываем путь к корневой папке проекта
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent  # P:\Python\finance-control

class GoogleCredentials(BaseModel):
    type: str = Field(..., alias="type")
    project_id: str = Field(..., alias="project_id")
    private_key_id: str = Field(..., alias="private_key_id")
    private_key: str = Field(..., alias="private_key")
    client_email: str = Field(..., alias="client_email")
    client_id: str = Field(..., alias="client_id")
    auth_uri: str = Field(..., alias="auth_uri")
    token_uri: str = Field(..., alias="token_uri")
    auth_provider_x509_cert_url: str = Field(..., alias="auth_provider_x509_cert_url")
    client_x509_cert_url: str = Field(..., alias="client_x509_cert_url")


class Config(BaseSettings):
    spreadsheet_url: str = Field(..., env="SPREADSHEET_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    gs_max_rows: int = Field(default=300, env="GS_MAX_ROWS")
    bot_token_main: Optional[str] = Field(default=None, env="BOT_TOKEN_MAIN")
    worksheet_name: str = Field(default="Общая таблица", env="WORKSHEET_NAME")
    google_credentials: GoogleCredentials

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("spreadsheet_url")
    @classmethod
    def extract_spreadsheet_id(cls, v: str) -> str:
        # Извлекаем ID из полного URL или возвращаем как есть, если это ID
        match = re.match(r"https://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", v)
        if match:
            return match.group(1)
        if re.match(r"[a-zA-Z0-9_-]+", v):
            return v
        raise ValueError("Invalid SPREADSHEET_URL format")

    @classmethod
    def parse_env(cls) -> "Config":
        try:
            creds_path = BASE_DIR / "creds.json"
            if creds_path.exists():
                with open(creds_path, "r", encoding="utf-8") as f:
                    creds_dict = json.load(f)
            else:
                creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS", "{}"))

            return cls(google_credentials=creds_dict)
        except ValidationError as e:
            logger.error(f"Configuration validation failed: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in GOOGLE_CREDENTIALS or creds.json: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise


# Инициализация конфигурации
config = Config.parse_env()

# Экспорт переменных для совместимости
SPREADSHEET_URL = config.spreadsheet_url
REDIS_URL = config.redis_url
GS_MAX_ROWS = config.gs_max_rows
BOT_TOKEN_MAIN = config.bot_token_main
WORKSHEET_NAME = config.worksheet_name
GOOGLE_CREDENTIALS = config.google_credentials.model_dump(by_alias=True)

# Настройка логирования с цветами
logger.remove()  # Удаляем все существующие обработчики
logger.add(
    lambda msg: print(msg, end=""),
    level="DEBUG",
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<b>{level:<8}</b> | "
        "<cyan>{name}:{function}:{line}</cyan> - "
        "<b>{message}</b>"
    ),
    colorize=True,
)

log = logger

log.info(f"Configuration loaded: SPREADSHEET_URL={SPREADSHEET_URL}, WORKSHEET_NAME={WORKSHEET_NAME}")