"""
Meta‑слой: строит «паспорт» таблицы (приходы, расходы, даты, балансы, кредиторы).
Никаких сумм — только коды, строки и столбцы.
"""
from __future__ import annotations
import re
import logging
from typing import Dict, Any, Tuple, List

from .gs_utils import open_worksheet

log = logging.getLogger(__name__)


class MetaDoc(dict):
    """см. структуру в docstring gs_utils.py"""


class SheetMeta:
    def __init__(self) -> None:
        self.ws, self.rows = open_worksheet()
        self.col_b = [r[1] if len(r) > 1 else "" for r in self.rows]
        self.col_c = [r[2] if len(r) > 2 else "" for r in self.rows]

    def _scan_balances(self, meta: MetaDoc) -> None:
        meta["balances"] = {
            "free": {"row": 3, "col": 4},  # D3
            "total": {"row": 3, "col": 5},  # E3
        }

    def _scan_dates(self, meta: MetaDoc) -> None:
        # строка с "П"
        try:
            in_idx = self.col_b.index("П")
        except ValueError:
            return
        # строка с "Р0"
        try:
            out_idx = self.col_b.index("Р0")
        except ValueError:
            out_idx = None

        # по любой из них считываем все даты и создаём mapping date->col
        date_cols: Dict[str, int] = {}
        pattern = re.compile(r"\d{2}\.\d{2}\.\d{4}")
        for row_idx in (in_idx, out_idx) if out_idx is not None else (in_idx,):
            row = self.rows[row_idx]
            for col_idx, cell in enumerate(row):
                if pattern.fullmatch(cell):
                    date_cols[cell] = col_idx + 1

        meta["date_cols"] = date_cols

    def _scan_income_tree(self, meta: MetaDoc) -> None:
        codes, names = self.col_b, self.col_c
        try:
            root = codes.index("П")
        except ValueError:
            meta["income"] = {}
            return

        income: Dict[str, Any] = {"П": {"row": root + 1, "cats": {}}}
        i, current = root + 1, ""
        while i < len(codes) and not codes[i].startswith("Итого"):
            code = codes[i]
            if code and "." not in code:
                income["П"]["cats"][code] = {"row": i + 1, "subs": {}}
                current = code
            elif current and code.startswith(f"{current}."):
                income["П"]["cats"][current]["subs"][code] = {"row": i + 1}
            i += 1

        meta["income"] = income

    def _scan_expense_tree(self, meta: MetaDoc) -> None:
        patt = re.compile(r"^Р\d+$")
        codes, names = self.col_b, self.col_c
        expenses: Dict[str, Any] = {}
        i = 0
        while i < len(codes):
            if patt.match(codes[i]):
                sec = codes[i]
                section: Dict[str, Any] = {"row": i + 1, "name": names[i], "cats": {}}
                j, current = i + 1, ""
                while j < len(codes) and not patt.match(codes[j]) and not codes[j].startswith("Итого"):
                    code = codes[j]
                    if code and "." not in code:
                        section["cats"][code] = {"row": j + 1, "subs": {}}
                        current = code
                    elif current and code.startswith(f"{current}."):
                        section["cats"][current]["subs"][code] = {"row": j + 1}
                    j += 1
                expenses[sec] = section
                i = j
            else:
                i += 1

        meta["expenses"] = expenses

    def _scan_creditors(self, meta: MetaDoc) -> None:
        codes, names = self.col_b, self.col_c
        cred: Dict[str, Any] = {}
        try:
            start = codes.index("К") + 1
            end = codes.index("Итоговая сумма экономии :", start)
        except ValueError:
            meta["creditors"] = {}
            return
        for idx in range(start, end, 5):
            name = names[idx].strip()
            if name:
                cred[name] = {"base": idx + 1}
        meta["creditors"] = cred

    def _month_headers(self, meta: MetaDoc) -> None:
        # строим mapping YYYY-MM -> column (balance/free share same)
        month_cols: Dict[str, Dict[str, int]] = {}
        for date_str, col in meta["date_cols"].items():
            d, m, y = date_str.split(".")
            ym = f"{y}-{m}"
            month_cols[ym] = {"balance": col, "free": col}
        meta["month_cols"] = month_cols

    def build_meta(self) -> MetaDoc:
        meta = MetaDoc()
        self._scan_balances(meta)
        self._scan_dates(meta)
        self._scan_income_tree(meta)
        self._scan_expense_tree(meta)
        self._scan_creditors(meta)
        self._month_headers(meta)
        return meta


if __name__ == "__main__":
    import pprint

    pprint.pprint(SheetMeta().build_meta(), width=140)
