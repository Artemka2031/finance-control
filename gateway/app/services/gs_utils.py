from __future__ import annotations

import functools
import logging
import os
import random
import time
from typing import Callable, Any, Tuple, List, Dict

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from gspread.utils import rowcol_to_a1

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
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

    def get_notes():
        service = build('sheets', 'v4', credentials=creds)
        response = service.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=["A1:ZZ300"],
            fields="sheets.data.rowData.values.note"
        ).execute()
        notes = {}
        for sheet in response.get('sheets', []):
            for row_idx, row in enumerate(sheet.get('data', [{}])[0].get('rowData', []), start=1):
                for col_idx, cell in enumerate(row.get('values', []), start=1):
                    note = cell.get('note', '')
                    if note:
                        cell_address = rowcol_to_a1(row_idx, col_idx)
                        notes[cell_address] = note
        return notes

    # Используем синхронный retry_gs
    sheet, rows = retry_gs(get_sheet_and_rows, retries=5)
    notes = retry_gs(get_notes, retries=5)

    log.info("Loaded %d rows from worksheet", len(rows))
    return sheet, rows, notes
