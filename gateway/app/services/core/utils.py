# gateway/app/services/core/utils.py
import functools
import random
import re
import time
from typing import Callable, Any, TypeVar

from googleapiclient.errors import HttpError

from .config import log


def timeit(tag: str | None = None):
    """Декоратор для замера времени выполнения."""

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

T = TypeVar('T')

def retry_gs(func: Callable[..., T]) -> Callable[..., T]:
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> T:
        retries = 5
        for i in range(retries):
            try:
                return func(*args, **kwargs)
            except HttpError as e:
                if e.resp.status not in (429, 500, 503):
                    raise
                delay = 2 ** i + random.random()
                log.warning("Google API %s → retry in %.1fs", e.resp.status, delay)
                time.sleep(delay)
        raise RuntimeError("Google API: too many retries")
    return wrapper


def to_a1(row: int, col: int) -> str:
    """Преобразует (row, col) в A1-нотацию."""
    col_str = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        col_str = chr(65 + rem) + col_str
    return f"{col_str}{row}"


def to_float(raw: str) -> float:
    """Преобразует строку в число."""
    if not raw or raw.strip() == '-':
        return 0.0
    cleaned = (
        raw.replace("\xa0", "").replace(" ", "").replace(",", ".").replace("₽", "").strip()
    )
    if cleaned == '-' or cleaned in (
            'Экстренныйрезерв',
            '1.Взяли/2.ПолучилиДОЛГ:',
            '1.Вернули/2.ДалиДОЛГ:',
            'СЭКОНОМИЛИ:',
            'ОСТАТОК-МЫСКОЛЬКОДОЛЖНЫ:'
    ) or cleaned.startswith('Итого'):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def format_formula(amount: float, current_formula: str, operation: str = "add") -> str:
    """Формирует формулу для ячейки."""
    value = f"{amount:.2f}".replace(".", ",")
    if operation == "add":
        if not current_formula:
            return f"={value}"
        return f"{current_formula}+{value}"
    else:  # remove
        # Ищем точное совпадение значения
        pattern = rf"\+{value}(?!\d)|^{value}(?!\d)"
        new_formula = re.sub(pattern, "", current_formula).strip("+")
        return new_formula or ""
