# gateway/app/services/core/connections.py
import asyncio
import random
import time
from typing import Dict, List, Tuple

import gspread
import gspread_asyncio
import redis.asyncio as aioredis
from gspread_asyncio import AsyncioGspreadClientManager
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import config, log
from .utils import retry_gs, timeit


REDIS: aioredis.Redis | None = None
AGS: AsyncioGspreadClientManager | None = None


def get_gs_creds() -> Credentials:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    return Credentials.from_service_account_info(
        config.google_credentials.model_dump(by_alias=True),
        scopes=scopes,
    )


async def get_redis() -> aioredis.Redis:
    global REDIS
    if REDIS is None:
        REDIS = aioredis.from_url(
            config.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        log.info(f"Connected to Redis at {config.redis_url}")
    return REDIS


def to_a1(row: int, col: int) -> str:
    """
    Преобразует (row, col) → адрес в A1-нотации.
    row, col начинаются с 1.
    """
    col_str = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        col_str = chr(65 + rem) + col_str
    return f"{col_str}{row}"


@retry_gs
def open_worksheet_sync() -> Tuple[gspread.Worksheet, List[List[str]], Dict[str, str]]:
    client = gspread.authorize(get_gs_creds())
    try:
        sheet = client.open_by_key(config.spreadsheet_url).worksheet(config.worksheet_name)
    except gspread.exceptions.SpreadsheetNotFound as e:
        log.error(f"Spreadsheet not found: {config.spreadsheet_url}. Ensure the ID is correct and accessible.")
        raise
    except gspread.exceptions.WorksheetNotFound as e:
        log.error(f"Worksheet '{config.worksheet_name}' not found in spreadsheet. Check the worksheet name.")
        raise

    def _fetch_rows():
        rows = sheet.get(f"A1:ZZ{config.gs_max_rows}")
        return sheet, rows

    def _fetch_notes(rows: List[List[str]]) -> Dict[str, str]:
        svc = build("sheets", "v4", credentials=get_gs_creds())
        resp = svc.spreadsheets().get(
            spreadsheetId=config.spreadsheet_url,
            ranges=[f"{config.worksheet_name}!A1:ZZ{config.gs_max_rows}"],
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
                    addr = to_a1(sheet_row_idx, col_idx)
                    notes[addr] = note
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
        ss = await agc.open_by_key(config.spreadsheet_url)
        return await ss.worksheet(config.worksheet_name)
    except gspread_asyncio.exceptions.APIError as e:
        log.error(f"Failed to open spreadsheet: {e}")
        raise
    except gspread_asyncio.exceptions.WorksheetNotFound as e:
        log.error(f"Worksheet '{config.worksheet_name}' not found in spreadsheet. Check the worksheet name.")
        raise


@timeit("close redis")
async def close_redis():
    global REDIS
    if REDIS:
        await REDIS.close()
        log.info("Redis connection closed")
        REDIS = None