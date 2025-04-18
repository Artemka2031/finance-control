# gateway/app/services/sheets_meta.py
"""
Meta‑слой: строит «паспорт» таблицы (приходы, расходы, даты, балансы, кредиторы).
Никаких сумм — только коды, строки и столбцы.
"""

from __future__ import annotations
import re, logging
from typing import Dict, List, Any, Optional

from gs_utils import open_worksheet

log = logging.getLogger(__name__)


class MetaDoc(dict):
    """см. описание структуры в docstring gs_utils.py"""


class SheetMeta:
    def __init__(self) -> None:
        self.ws, self.rows = open_worksheet()
        self.col_b: List[str] = [r[1] if len(r) > 1 else "" for r in self.rows]
        self.col_c: List[str] = [r[2] if len(r) > 2 else "" for r in self.rows]

    # ─── Баланс / свободные средства (E3 / D3) ───
    def _scan_balances(self, meta: MetaDoc) -> None:
        meta["balances"] = {
            "free":  {"row": 3, "col": 4},  # D3
            "total": {"row": 3, "col": 5},  # E3
        }

    # ─── Даты‑столбцы (приходы : строка с 'П', расходы : строка с 'Р0') ───
    def _scan_dates(self, meta: MetaDoc) -> None:
        meta["dates"] = {"incoming": [], "outgoing": []}

        def extract_dates(row: list[str]) -> list[str]:
            return [d for d in row[6:] if re.match(r"\d{2}\.\d{2}\.\d{4}", d)]

        try:
            in_row = self.col_b.index("П")
            meta["dates"]["incoming"] = extract_dates(self.rows[in_row])
        except ValueError:
            pass

        try:
            out_row = self.col_b.index("Р0")
            meta["dates"]["outgoing"] = extract_dates(self.rows[out_row])
        except ValueError:
            pass

    # ─── Приходы ───
    def _scan_income_tree(self, meta: MetaDoc) -> None:
        codes, names = self.col_b, self.col_c
        income: Dict[str, Any] = {}
        try:
            root = codes.index("П")
        except ValueError:
            meta["income"] = {}
            return

        income["П"] = {"row": root + 1, "cats": {}}
        i, cat_code = root + 1, ""
        while i < len(codes) and not codes[i].startswith("Итого"):
            code = codes[i]
            if code and "." not in code:
                income["П"]["cats"][code] = {"row": i + 1, "subs": {}}
                cat_code = code
            elif code.startswith(f"{cat_code}."):
                income["П"]["cats"][cat_code]["subs"][code] = {"row": i + 1}
            i += 1
        meta["income"] = income

    # ─── Расходы ───
    def _scan_expense_tree(self, meta: MetaDoc) -> None:
        patt_r = re.compile(r"^Р\d+$")
        codes, names = self.col_b, self.col_c
        expenses: Dict[str, Any] = {}
        i = 0
        while i < len(codes):
            if patt_r.match(codes[i]):
                sec_code = codes[i]
                section = {"row": i + 1, "name": names[i], "cats": {}}
                j, cat_code = i + 1, ""
                while j < len(codes) and not patt_r.match(codes[j]):
                    if codes[j].startswith("Итого"):
                        break
                    if codes[j] and "." not in codes[j]:
                        section["cats"][codes[j]] = {"row": j + 1, "subs": {}}
                        cat_code = codes[j]
                    elif codes[j].startswith(f"{cat_code}."):
                        section["cats"][cat_code]["subs"][codes[j]] = {"row": j + 1}
                    j += 1
                expenses[sec_code] = section
                i = j
            else:
                i += 1
        meta["expenses"] = expenses

    # ─── Кредиторы ───
    def _scan_creditors(self, meta: MetaDoc) -> None:
        codes, names = self.col_b, self.col_c
        meta["creditors"] = {}
        try:
            start = codes.index("К") + 1
            end   = codes.index("Итоговая сумма экономии :", start)
        except ValueError:
            return
        for i in range(start, end, 5):
            cred = names[i].strip()
            if cred:
                meta["creditors"][cred] = {"base": i + 1}

    # ─── Главный конструктор ───
    def build_meta(self) -> MetaDoc:
        meta: MetaDoc = MetaDoc()
        self._scan_balances(meta)
        self._scan_dates(meta)
        self._scan_income_tree(meta)
        self._scan_expense_tree(meta)
        self._scan_creditors(meta)
        return meta


# CLI‑проверка
if __name__ == "__main__":
    import pprint, json
    meta = SheetMeta().build_meta()
    pprint.pprint(meta, width=140)
