from __future__ import annotations

import os
import time
import functools
import logging
import random
from typing import Callable, Any, Tuple, List, Dict

from dotenv import load_dotenv
import gspread
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv(".env")
log = logging.getLogger(__name__)


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


def retry_gs(func: Callable[[], Any], *, retries: int = 5) -> Any:
    """
    Синхронный вызов Google API с экспоненциальным back-off для обработки ошибок 429/5xx.
    """
    for i in range(retries):
        try:
            return func()
        except HttpError as e:
            if e.resp.status not in (429, 500, 503):
                raise
            delay = 2 ** i + random.random()
            log.warning("Google API %s → retry in %.1fs", e.resp.status, delay)
            time.sleep(delay)
    raise RuntimeError("Google API: too many retries")


def to_a1(row: int, col: int) -> str:
    """
    Преобразует координаты (row, col) в адрес A1 (например, row=6, col=32 → 'AF6').
    row: номер строки (начинается с 1).
    col: номер столбца (начинается с 1).
    """
    col_str = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        col_str = chr(65 + remainder) + col_str
    return f"{col_str}{row}"


def _is_numeric_value(raw: str) -> bool:
    """Проверяет, является ли значение числовым (аналогично _to_float в sheets_numeric)."""
    if not raw or raw.strip() == '-':
        return False
    cleaned = (
        raw.replace("\xa0", "")
        .replace(" ", "")
        .replace(",", ".")
        .replace("₽", "")
        .strip()
    )
    if cleaned == '-' or cleaned in (
            'Экстренныйрезерв',
            '1.Взяли/2.ПолучилиДОЛГ:',
            '1.Вернули/2.ДалиДОЛГ:',
            'СЭКОНОМИЛИ:',
            'ОСТАТОК-МЫСКОЛЬКОДОЛЖНЫ:'
    ) or cleaned.startswith('Итого'):
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


# ───────────── Google Sheets I/O ─────────────
def _client():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_file(
        os.getenv("SHEETS_SERVICE_FILE", "creds.json"),
        scopes=scopes
    )
    # Явно отключаем file_cache для gspread
    return gspread.authorize(creds), creds


@timeit("open_worksheet")
def open_worksheet() -> Tuple[gspread.Worksheet, List[List[str]], Dict[str, str]]:
    client, creds = _client()
    sheet_id = os.getenv("SPREADSHEET_URL")
    if not sheet_id:
        raise ValueError("SPREADSHEET_URL is not set in .env")

    def get_sheet_and_rows():
        try:
            sheet = client.open_by_key(sheet_id).worksheet("Общая таблица")
            rows = sheet.get("A1:ZZ300")
            # Удаляем пустые строки в конце
            rows = [row for row in rows if any(cell.strip() for cell in row)]
            return sheet, rows
        except gspread.exceptions.SpreadsheetNotFound:
            log.error("Spreadsheet with ID %s not found or inaccessible", sheet_id)
            raise

    def get_notes(rows: List[List[str]]):
        service = build('sheets', 'v4', credentials=creds)
        response = service.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=["Общая таблица!A1:ZZ300"],
            fields="sheets.data.rowData.values.note"
        ).execute()
        notes = {}
        # Обрабатываем все строки из ответа API
        for sheet_row_idx, row in enumerate(response.get('sheets', [{}])[0].get('data', [{}])[0].get('rowData', []),
                                            start=1):
            # Проверяем, есть ли соответствующая строка в rows
            mapped_row_idx = sheet_row_idx  # Прямое соответствие строк
            row_data = rows[sheet_row_idx - 1] if sheet_row_idx <= len(rows) else []
            for col_idx, cell in enumerate(row.get('values', []), start=1):
                note = cell.get('note', '')
                if note and col_idx <= len(row_data) and _is_numeric_value(row_data[col_idx - 1]):
                    # Формируем адрес A1
                    cell_key = to_a1(sheet_row_idx, col_idx)
                    notes[cell_key] = note
                    log.debug(
                        f"Loaded note for {cell_key} (sheet row={sheet_row_idx}, col={col_idx}, value={row_data[col_idx - 1]!r}): {note!r}")
        log.debug(f"Total notes loaded: {len(notes)}")
        return notes

    # Используем синхронный retry_gs
    sheet, rows = retry_gs(get_sheet_and_rows, retries=5)
    notes = retry_gs(lambda: get_notes(rows), retries=5)

    log.info("Loaded %d rows from worksheet", len(rows))
    return sheet, rows, notes
