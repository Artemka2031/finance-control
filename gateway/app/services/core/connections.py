import re
from typing import Dict, List, Tuple

import gspread
import gspread_asyncio
import redis.asyncio as aioredis
from gspread_asyncio import AsyncioGspreadClientManager
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .config import (
    GOOGLE_CREDENTIALS,
    SPREADSHEET_URL,
    WORKSHEET_NAME,
    GS_MAX_ROWS,
    REDIS_URL,
    log,
)
from .utils import retry_gs, timeit

REDIS: aioredis.Redis | None = None
AGS: AsyncioGspreadClientManager | None = None


def _extract_spreadsheet_id(url: str) -> str:
    """Извлекает ID таблицы из полного URL."""
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else url


def get_gs_creds() -> Credentials:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    return Credentials.from_service_account_info(
        GOOGLE_CREDENTIALS,
        scopes=scopes,
    )


async def get_redis() -> aioredis.Redis:
    global REDIS
    if REDIS is None:
        REDIS = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        log.info(f"Connected to Redis at {REDIS_URL}")
    return REDIS


def to_a1(row: int, col: int) -> str:
    """(row, col) → A1‑нотация, отсчёт с 1."""
    col_str = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        col_str = chr(65 + rem) + col_str
    return f"{col_str}{row}"


@retry_gs
def open_worksheet_sync() -> Tuple[gspread.Worksheet, List[List[str]], Dict[str, str]]:
    client = gspread.authorize(get_gs_creds())
    sheet_id = _extract_spreadsheet_id(SPREADSHEET_URL)

    try:
        sheet = client.open_by_url(SPREADSHEET_URL).worksheet(WORKSHEET_NAME)
    except gspread.exceptions.SpreadsheetNotFound:
        log.error(f"Spreadsheet not found: {SPREADSHEET_URL}")
        raise
    except gspread.exceptions.WorksheetNotFound:
        log.error(f"Worksheet '{WORKSHEET_NAME}' not found")
        raise

    def _fetch_rows():
        rows = sheet.get(f"A1:ZZ{GS_MAX_ROWS}")
        return sheet, rows

    def _fetch_notes(rows: List[List[str]]) -> Dict[str, str]:
        svc = build("sheets", "v4", credentials=get_gs_creds())
        resp = svc.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=[f"{WORKSHEET_NAME}!A1:ZZ{GS_MAX_ROWS}"],
            fields="sheets.data.rowData.values.note",
        ).execute()

        notes: Dict[str, str] = {}
        for sheet_row_idx, row in enumerate(
            resp.get("sheets", [{}])[0].get("data", [{}])[0].get("rowData", []),
            start=1,
        ):
            for col_idx, cell in enumerate(row.get("values", []), start=1):
                note = cell.get("note", "")
                if note:
                    notes[to_a1(sheet_row_idx, col_idx)] = note
        log.debug("Total notes loaded: %d", len(notes))
        return notes

    sheet, rows = _fetch_rows()
    notes = retry_gs(lambda: _fetch_notes(rows))()
    log.info(f"Loaded {len(rows)} rows, {len(notes)} notes")
    return sheet, rows, notes


async def get_async_worksheet() -> gspread_asyncio.AsyncioGspreadWorksheet:
    global AGS
    if AGS is None:
        AGS = AsyncioGspreadClientManager(get_gs_creds)
    agc = await AGS.authorize()

    try:
        ss = await agc.open_by_url(SPREADSHEET_URL)
        return await ss.worksheet(WORKSHEET_NAME)
    except gspread_asyncio.exceptions.APIError as e:
        log.error(f"Failed to open spreadsheet: {e}")
        raise
    except gspread_asyncio.exceptions.WorksheetNotFound:
        log.error(f"Worksheet '{WORKSHEET_NAME}' not found")
        raise


@timeit("close redis")
async def close_redis():
    global REDIS
    if REDIS:
        await REDIS.close()
        log.info("Redis connection closed")
        REDIS = None
