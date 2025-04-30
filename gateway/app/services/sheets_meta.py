# gateway/app/services/sheets_meta.py
from __future__ import annotations

import asyncio
import json
import logging
import os
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
        if rows is None:
            self.ws, self.rows, self.notes = open_worksheet()
        else:
            self.ws, self.rows, self.notes = None, rows, {}
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
        meta.setdefault("date_cols", {})
        meta.setdefault("month_cols", {})

        def push_dates(row_idx: int) -> None:
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
                        ym = f"{yyyy}-{mm.zfill(2)}"
                        if meta["month_cols"].get(ym) is None:
                            meta["month_cols"][ym] = {"balance": col, "free": col}
                elif "Промежуточные" in cell:
                    ym_match = re.search(r'(\w+\.\d{4})', cell)
                    if ym_match:
                        mon = ym_match.group(1)
                        mon_mm, mon_yy = mon.split(".")
                        ym = f"{mon_yy}-{self._month_to_num(mon_mm)}"
                        meta["month_cols"][ym] = {"balance": c + 1, "free": c + 1}

        push_dates(self._index_in_col_b("П"))
        push_dates(self._index_in_col_b("Р0"))

    def _month_to_num(self, month_abbr: str) -> str:
        month_map = {
            'янв': '01', 'февр': '02', 'мар': '03', 'апр': '04', 'май': '05',
            'июн': '06', 'июл': '07', 'авг': '08', 'сент': '09', 'окт': '10',
            'нояб': '11', 'дек': '12'
        }
        return month_map.get(month_abbr.lower(), '00')

    # ───────────── ПРИХОДЫ (flat‑tree без разделов) ─────────────
    def _scan_income_tree(self, meta: MetaDoc) -> None:
        root = self._index_in_col_b("П")
        cats: dict[str, Any] = {}
        cat_code = ""
        log.info("Scanning income tree starting from row %d", root + 1)
        for i in tqdm(range(root + 1, len(self.col_b)), desc="Scanning income"):
            if self.col_b[i].startswith("Итого"):
                meta["income"] = {"cats": cats, "total_row": i + 1}
                break
            code = self.col_b[i]
            if code and "." not in code:
                cats[code] = {"name": self.col_c[i], "row": i + 1, "subs": {}}
                cat_code = code
            elif cat_code and code.startswith(f"{cat_code}."):
                cats[cat_code]["subs"][code] = {"name": self.col_c[i], "row": i + 1}
        if "income" not in meta:
            meta["income"] = {"cats": cats, "total_row": root + 1}

    # ───────────── РАСХОДЫ (раздел → категории → подкатегории) ─────────────
    def _scan_expense_tree(self) -> None:
        patt_section = re.compile(r"^Р\d+$")
        expenses = {}
        i = 0
        log.info("Scanning expense tree")
        while i < len(self.col_b):
            sec_code = self.col_b[i]
            if not patt_section.match(sec_code):
                i += 1
                continue
            section = {
                "name": self.col_c[i],
                "row": i + 1,
                "cats": {}
            }
            cat_code = ""
            j = i + 1
            while j < len(self.col_b):
                code = self.col_b[j]
                if patt_section.match(code):
                    break
                if code == "Итого по всем разделам:":
                    self.meta["expenses"]["total_row"] = j + 1
                    break
                if code.startswith("Итого"):
                    section["row_end"] = j + 1
                    section["total_row"] = j + 1
                    break
                if code and "." not in code:
                    section["cats"][code] = {"name": self.col_c[j], "row": j + 1, "subs": {}}
                    cat_code = code
                elif cat_code and code.startswith(f"{cat_code}."):
                    section["cats"][cat_code]["subs"][code] = {"name": self.col_c[j], "row": j + 1}
                j += 1
            expenses[sec_code] = section
            i = j
        self.meta["expenses"] = expenses
        if expenses and "total_row" not in self.meta["expenses"]:
            last_section = max(expenses.values(), key=lambda x: x["row"])
            self.meta["expenses"]["total_row"] = last_section.get("row_end", last_section["row"] + 1)
        log.info(f"Expense sections: {list(expenses.keys())}")
        if "total_row" in self.meta["expenses"]:
            log.info(f"Total row for expenses: {self.meta['expenses']['total_row']}")

    # ───────────── КРЕДИТОРЫ ─────────────
    def _scan_creditors(self, meta: MetaDoc) -> None:
        codes, names = self.col_b, self.col_c
        try:
            start = codes.index("К") + 1
            end = codes.index("Итоговая сумма экономии :", start)
        except ValueError:
            meta["creditors"] = {}
            return
        exclude_creditors = [
            "ВЗЯЛИ В ДОЛГ :",
            "ВЕРНУЛИ ДОЛГ :",
            "СЭКОНОМИЛИ :",
            "ОСТАТОК - МЫ СКОЛЬКО ДОЛЖНЫ :"
        ]
        creditors = {}
        for i in range(start, end, 5):
            name = names[i].strip()
            if name and name not in exclude_creditors:
                creditors[name] = {"base": i + 1}
        meta["creditors"] = creditors

    # ───────────── МЕТОД-ПУСТЫШКА ─────────────
    def _scan_month_subtotals(self, meta: MetaDoc) -> None:
        pass

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
    import pprint

    async def _demo():
        rows = None
        if path := os.getenv("DEBUG_ROWS"):
            rows = json.loads(open(path, "r", encoding="utf-8").read())
        meta = SheetMeta(rows).build_meta()
        pprint.pp(meta, width=140)

    asyncio.run(_demo())