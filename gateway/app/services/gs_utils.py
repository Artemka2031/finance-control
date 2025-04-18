# gateway/app/services/gs_utils.py
"""
Общие вспомогательные вещи для работы с Google Sheets:
• авторизация и получение worksheet
• конвертация номера столбца → буква (A, AA…)
Эти функции импортируются в других модулях (sheets_meta и далее).
"""

from __future__ import annotations
import os, logging
from typing import Tuple
import pygsheets
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def col_to_letter(idx: int) -> str:
    """1 → 'A',  28 → 'AB'."""
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def open_worksheet() -> Tuple[pygsheets.Worksheet, list[list[str]]]:
    """
    Отдаёт Worksheet «Общая таблица» и уже загруженные строки.
    Переменные окружения:
      • SHEETS_SERVICE_FILE – JSON service‑account (по умолчанию ./creds.json)
      • SPREADSHEET_URL     – ссылка на таблицу (обязательно)
    """
    creds = os.getenv("SHEETS_SERVICE_FILE", "./creds.json")
    url   = os.getenv("SPREADSHEET_URL")
    if not url:
        raise RuntimeError("Переменная SPREADSHEET_URL не найдена")

    gc = pygsheets.authorize(service_file=creds)
    sh = gc.open_by_url(url)
    ws = sh.worksheet_by_title("Общая таблица")
    rows = ws.get_all_values(include_tailing_empty=False)
    log.info("📄 Worksheet loaded: %s", url)
    return ws, rows
