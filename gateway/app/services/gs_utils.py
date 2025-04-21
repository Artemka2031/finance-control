# gateway/app/services/gs_utils.py
"""
💡 Вспомогательный слой: подгрузка .env, авторизация, чтение листа одним запросом,
   декоратор‑таймер и retry c экспоненциальной задержкой.
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
import pygsheets
from googleapiclient.errors import HttpError

# подгружаем .env
load_dotenv()

log = logging.getLogger(__name__)


def timeit(tag: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """@timeit("msg") → печатает длительность вызова"""

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
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
    Безопасный вызов Google API с back‑off при 429/5xx.
    `coro` – async‑или sync‑функция без аргументов.
    """
    for i in range(retries):
        try:
            if asyncio.iscoroutinefunction(coro):
                return await coro()
            return coro()
        except HttpError as e:
            if e.resp.status not in (429, 500, 503):
                raise
            delay = 2 ** i + random.random()
            log.warning("Google API %s → retry in %.1fs", e.resp.status, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("Google API: too many retries")


@timeit("open_worksheet")
def open_worksheet() -> Tuple[pygsheets.Worksheet, List[List[str]]]:
    """
    Открывает лист «Общая таблица» и возвращает (ws, all_rows).
    """
    creds = os.getenv("SHEETS_SERVICE_FILE", "creds.json")
    url = os.getenv("SPREADSHEET_URL")
    if not url:
        raise EnvironmentError("SPREADSHEET_URL not set")

    gc = pygsheets.authorize(service_file=creds)
    sh = gc.open_by_url(url)
    ws = sh.worksheet_by_title("Общая таблица")
    rows: List[List[str]] = ws.get_all_values(include_tailing_empty=False)
    return ws, rows
