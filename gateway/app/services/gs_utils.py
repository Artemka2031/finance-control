"""
I/O-шлюз к Google Sheets.

▪ .env-параметры
      SHEETS_SERVICE_FILE   JSON-ключ сервис-аккаунта – по умолчанию ./creds.json
      SPREADSHEET_URL       ID таблицы (например, 1VPxgpVwQjtdDuqbFaOSAc9Nfj1a4EYnba7FvaJgvN2g)
▪ open_worksheet()          1 HTTP-запрос → все строки листа «main» (до 300 строк)
▪ декоратор @timeit         печать длительности вызова
▪ retry_gs()                экспоненциальный back-off при 429/5xx
"""

from __future__ import annotations

import os
import time
import functools
import logging
import asyncio
import random
from typing import Callable, Any, Tuple, List

from dotenv import load_dotenv
import gspread
from googleapiclient.errors import HttpError
from oauth2client.service_account import ServiceAccountCredentials

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv(".env")
log = logging.getLogger(__name__)


# ────────────────────────── google sheets ──────────────────────────
def _client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    return gspread.authorize(creds)


# ───────────── helpers ─────────────
def timeit(tag: str | None = None):
    """@timeit('msg') – логируем, за сколько отработала функция."""

    def deco(func: Callable[..., Any]):
        label = tag or func.__name__

        @functools.wraps(func)
        def wrap(*a, **kw):
            t0 = time.perf_counter()
            try:
                return func(*a, **kw)
            finally:
                log.info("⏱ %s  %.3f s", label, time.perf_counter() - t0)

        return wrap

    return deco


async def retry_gs(coro: Callable[[], Any], *, retries: int = 5) -> Any:
    """
    Безопасный вызов Google API с экспоненциальным back-off. Работает и с sync-,
    и с async-корутинами.
    """
    for i in range(retries):
        try:
            return await coro() if asyncio.iscoroutinefunction(coro) else coro()
        except HttpError as e:
            if e.resp.status not in (429, 500, 503):
                raise
            delay = 2 ** i + random.random()
            log.warning("Google API %s → retry in %.1fs", e.resp.status, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("Google API: too many retries")


# ───────────── Google Sheets I/O ─────────────
@timeit("open_worksheet")
def open_worksheet() -> Tuple[gspread.Worksheet, List[List[str]]]:
    client = _client()
    sheet_id = os.getenv("SPREADSHEET_URL")
    if not sheet_id:
        raise ValueError("SPREADSHEET_URL is not set in .env")
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Общая таблица")
    except gspread.exceptions.SpreadsheetNotFound:
        log.error("Spreadsheet with ID %s not found or inaccessible", sheet_id)
        raise
    # Загружаем только первые 300 строк
    rows: List[List[str]] = sheet.get("A1:ZZ300")
    # Удаляем пустые строки в конце
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    log.info("Loaded %d rows from worksheet", len(rows))
    return sheet, rows
