# gateway/app/services/gs_utils.py
# -*- coding: utf-8 -*-
"""
Google-Sheets helper: открывает лист «Общая таблица», возвращает
  - объект Worksheet (gspread)
  - все строки (list[list[str]])
  - словарь заметок { "A1" : "note text" }

$ python -m gateway.app.services.gs_utils --help      # CLI-диагностика
"""
from __future__ import annotations

import functools
import logging
import os
import random
import time
from typing import Any, Callable, Dict, List, Tuple

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ─────────────────────────── env / logging ────────────────────────────────
load_dotenv(".env")  # путь к .env на уровень выше
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# сколько строк считывать из таблицы; меняйте в одном месте
MAX_ROWS = int(os.getenv("GS_MAX_ROWS", "300"))  # A1:ZZ300


# ───────────────────────────── helpers ────────────────────────────────────
def timeit(tag: str | None = None):
    """@timeit('msg') – простая метка времени выполнения функции."""
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
    Выполняет вызов Google-API с экспоненциальным back-off.
    Повторяет 429/5xx максимум `retries` раз.
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
    Преобразует (row, col) → адрес в A1-нотации.
    row, col начинаются с 1.
    """
    col_str = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        col_str = chr(65 + rem) + col_str
    return f"{col_str}{row}"


# ─────────────────────── Google Sheets access ─────────────────────────────
def _client() -> Tuple[gspread.Client, Credentials]:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(
        os.getenv("SHEETS_SERVICE_FILE", "creds.json"),
        scopes=scopes,
    )
    return gspread.authorize(creds), creds


@timeit("open_worksheet")
def open_worksheet() -> Tuple[gspread.Worksheet, List[List[str]], Dict[str, str]]:
    client, creds = _client()
    sheet_id = os.getenv("SPREADSHEET_URL")
    if not sheet_id:
        raise ValueError("SPREADSHEET_URL is not set in .env")

    def _fetch_rows():
        sheet = client.open_by_key(sheet_id).worksheet("Общая таблица")
        rows = sheet.get(f"A1:ZZ{MAX_ROWS}")
        return sheet, rows  # Не фильтруем пустые строки

    def _fetch_notes(rows: List[List[str]]) -> Dict[str, str]:
        svc = build("sheets", "v4", credentials=creds)
        resp = svc.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=[f"Общая таблица!A1:ZZ{MAX_ROWS}"],
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

    sheet, rows = retry_gs(_fetch_rows)
    notes = retry_gs(lambda: _fetch_notes(rows))
    log.info("Loaded %d rows, %d notes", len(rows), len(notes))
    return sheet, rows, notes


# ───────────────────────────── CLI utility ───────────────────────────────
if __name__ == "__main__":
    """
    Быстрый self-check модуля для проверки связи между матрицей значений и заметок.
      $ python -m gateway.app.services.gs_utils --show 30 --push-redis
      $ docker exec finance-redis redis-cli FLUSHALL   # обнулить кеш
    """
    import argparse
    import asyncio
    import re
    import redis.asyncio as aioredis


    def parse_a1_address(addr: str) -> tuple[int, int]:
        """Разбирает адрес A1 (например, 'AF6') в (row, col)."""
        match = re.match(r"([A-Z]+)(\d+)", addr)
        if not match:
            return 0, 0
        col_str, row_str = match.groups()
        col = 0
        for char in col_str:
            col = col * 26 + (ord(char) - ord('A') + 1)
        row = int(row_str)
        return row, col


    p = argparse.ArgumentParser("gs_utils quick-check")
    p.add_argument("--show", type=int, default=20,
                   help="Показать N первых заметок с соответствующими значениями")
    p.add_argument("--push-redis", action="store_true",
                   help="Сохранить заметки в Redis (ключи comment:<A1>)")
    args = p.parse_args()

    ws, rows, notes = open_worksheet()
    print(f"✔️  Worksheet title : {ws.title!r}")
    print(f"ℹ️  Rows loaded      : {len(rows)}")
    print(f"📝 Notes discovered  : {len(notes)}")

    # Печатаем первые N заметок с соответствующими значениями
    print("\n🔍 Checking notes and corresponding values:")
    for i, (addr, txt) in enumerate(notes.items()):
        if i >= args.show:
            break
        # Разбираем адрес A1 в row, col
        row, col = parse_a1_address(addr)
        # Корректируем для 0-based индексов в rows
        row_idx = row - 1
        col_idx = col - 1
        value = "<out of bounds>"
        if row_idx < len(rows) and col_idx < len(rows[row_idx]):
            value = rows[row_idx][col_idx].strip() if rows[row_idx][col_idx] else "<empty>"
        print(f"{addr:<6} → Note: {txt[:80]!r:<80} | Value: {value!r}")

    # Опционально пушим в Redis
    if args.push_redis:
        async def _push():
            r = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                                  encoding="utf-8", decode_responses=True)
            pipe = r.pipeline()
            for addr, txt in notes.items():
                pipe.set(f"comment:{addr}", txt, ex=3600)
            await pipe.execute()
            await r.close()
            print(f"✅ {len(notes)} notes cached to Redis")


        asyncio.run(_push())
