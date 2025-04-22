"""
Meta‑слой: «паспорт» таблицы – только структуры, НИКАКИХ сумм.
Строится из массива rows, полученного одним запросом.
"""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Dict, Any, List

from tqdm import tqdm
from .gs_utils import open_worksheet

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
MetaDoc = Dict[str, Any]


class SheetMeta:
    def __init__(self, rows: List[List[str]] | None = None):
        log.info("Initializing SheetMeta with %d rows", len(rows) if rows else 0)
        self.ws, self.rows = open_worksheet() if rows is None else (None, rows)
        self.col_b = [r[1] if len(r) > 1 else "" for r in tqdm(self.rows, desc="Building col_b")]
        self.col_c = [r[2] if len(r) > 2 else "" for r in tqdm(self.rows, desc="Building col_c")]

    def _index_in_col_b(self, needle: str) -> int:
        return self.col_b.index(needle)

    # ───────────── балансы ─────────────
    @staticmethod
    def _scan_balances(meta: MetaDoc) -> None:
        meta["balances"] = {
            "free": {"row": 3, "col": 4},  # D3
            "total": {"row": 3, "col": 5},  # E3
        }

    # ───────────── ДАТЫ → date_cols + month_cols + month_subtotals ──────────
    def _scan_date_columns(self, meta: MetaDoc) -> None:
        """
        Заполняет:
            meta["date_cols"]  = {'01.11.2024': 8, ...}
            meta["month_cols"] = {'2024-11': {'balance': 8, 'free': 8}, ...}
            meta["month_subtotals"] = {'2024-11': {'income': 8, 'expense': 8}, ...}
        """
        meta.setdefault("date_cols", {})
        meta.setdefault("month_cols", {})
        meta.setdefault("month_subtotals", {})

        def push_dates(row_idx: int, is_income: bool) -> None:
            if row_idx is None:
                return
            row = self.rows[row_idx]
            for c in range(6, len(row)):
                cell = row[c].strip()
                if re.match(r"^\d{2}\.\d{2}\.\d{4}$", cell):
                    col = c + 1
                    meta["date_cols"][cell] = col
                    parts = cell.split(".")
                    if len(parts) == 3:
                        _, mm, yyyy = parts
                        ym = f"{yyyy}-{mm}"
                        meta["month_cols"].setdefault(ym, {"balance": col, "free": col})
                    else:
                        log.warning("Unexpected date format %r at row %d, col %d", cell, row_idx + 1, col)
                elif "Промежуточные" in cell:
                    ym_match = re.search(r'(\w+\.\d{4})', cell)
                    if ym_match:
                        mon = ym_match.group(1)
                        mon_mm, mon_yy = mon.split(".")
                        ym = f"{mon_yy}-{mon_mm.zfill(2)}"
                        key = "income" if is_income else "expense"
                        meta["month_subtotals"].setdefault(ym, {})[key] = c + 1

        push_dates(self._index_in_col_b("П"), is_income=True)
        push_dates(self._index_in_col_b("Р0"), is_income=False)

    # ───────────── ПРИХОДЫ (flat‑tree без разделов) ─────────────
    def _scan_income_tree(self, meta: MetaDoc) -> None:
        root = self._index_in_col_b("П")
        cats: dict[str, Any] = {}
        cat_code = ""
        log.info("Scanning income tree starting from row %d", root + 1)
        for i in tqdm(range(root + 1, len(self.col_b)), desc="Scanning income"):
            if self.col_b[i].startswith("Итого"):
                break
            code = self.col_b[i]
            if code and "." not in code:
                cats[code] = {"name": self.col_c[i], "row": i + 1, "subs": {}}
                cat_code = code
            elif cat_code and code.startswith(f"{cat_code}."):
                cats[cat_code]["subs"][code] = {"name": self.col_c[i], "row": i + 1}
        meta["income"] = {"cats": cats}

    # ───────────── РАСХОДЫ (раздел → категории → подкатегории) ─────────────
    def _scan_expense_tree(self, meta: MetaDoc) -> None:
        patt_section = re.compile(r"^Р\d+$")
        expenses: dict[str, Any] = {}
        i = 0
        log.info("Scanning expense tree")
        while i < len(self.col_b):
            sec_code = self.col_b[i]
            if not patt_section.match(sec_code):
                i += 1
                continue
            section: dict[str, Any] = {
                "name": self.col_c[i],
                "row": i + 1,
                "cats": {}
            }
            cat_code = ""
            j = i + 1
            with tqdm(total=len(self.col_b) - j, desc=f"Scanning section {sec_code}") as pbar:
                while j < len(self.col_b):
                    code = self.col_b[j]
                    if patt_section.match(code):
                        break
                    if code.startswith("Итого"):
                        section["row_end"] = j + 1
                        j += 1
                        break
                    if code and "." not in code:
                        section["cats"][code] = {"name": self.col_c[j], "row": j + 1, "subs": {}}
                        cat_code = code
                    elif cat_code and code.startswith(f"{cat_code}."):
                        section["cats"][cat_code]["subs"][code] = {"name": self.col_c[j], "row": j + 1}
                    j += 1
                    pbar.update(1)
            expenses[sec_code] = section
            i = j
        meta["expenses"] = expenses

    # ───────────── КРЕДИТОРЫ ─────────────
    def _scan_creditors(self, meta: MetaDoc) -> None:
        codes, names = self.col_b, self.col_c
        try:
            start = codes.index("К") + 1
            end = codes.index("Итоговая сумма экономии :", start)
        except ValueError:
            meta["creditors"] = {}
            return
        creditors = {}
        for i in range(start, end, 5):
            name = names[i].strip()
            if name:
                creditors[name] = {"base": i + 1}
        meta["creditors"] = creditors

    # ───────────── МЕТОД-ПУСТЫШКА ─────────────
    def _scan_month_subtotals(self, meta: MetaDoc) -> None:
        # оставить для совместимости, фактически handled in _scan_date_columns
        ...

    # ───────────── СБОРКА META ─────────────
    def build_meta(self) -> MetaDoc:
        meta: MetaDoc = {}
        self._scan_balances(meta)
        self._scan_date_columns(meta)
        self._scan_income_tree(meta)
        self._scan_expense_tree(meta)
        self._scan_creditors(meta)
        meta.setdefault("month_subtotals", {})
        return meta


# ───────────── CLI‑демо ─────────────
if __name__ == "__main__":
    import pprint, json, os


    async def _demo():
        rows = None
        if path := os.getenv("DEBUG_ROWS"):
            rows = json.loads(open(path, "r", encoding="utf-8").read())
        meta = SheetMeta(rows).build_meta()
        pprint.pp(meta, width=140)


    asyncio.run(_demo())
