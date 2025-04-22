from __future__ import annotations

import os
import json
import asyncio
import logging
from typing import Any, Callable, Dict, List, Literal
from datetime import datetime, timedelta

import redis.asyncio as aioredis
from dotenv import load_dotenv
from tqdm import tqdm

from .gs_utils import open_worksheet, timeit
from .sheets_meta import SheetMeta

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv(".env")
log = logging.getLogger(__name__)


# ────────────────────────── service class ──────────────────────────
class SheetNumeric:
    def __init__(self) -> None:
        self.ws, self.rows = open_worksheet()
        log.info("Loaded %d rows from Google Sheets", len(self.rows))
        self.meta = SheetMeta(self.rows).build_meta()
        log.info("Building float matrix for %d rows", len(self.rows))
        self.matrix: List[List[float]] = []
        for row_idx, row in enumerate(tqdm(self.rows, desc="Converting to float matrix")):
            row_values = [self._to_float(c, row_idx + 1, col_idx + 1) for col_idx, c in enumerate(row)]
            self.matrix.append(row_values)
        self.redis = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            encoding="utf-8",
            decode_responses=True,
        )

    # ─── helpers ───────────────────────────────────────────────────
    def _to_float(self, raw: str, row: int, col: int) -> float:
        if not raw or raw.strip() == '-':
            return 0.0
        cleaned = (
            raw.replace("\xa0", "")
            .replace(" ", "")
            .replace(",", ".")
            .replace("₽", "")
            .strip()
        )
        log.debug(f"Row {row}, Col {col}: Converting raw value {raw!r} to float: cleaned = {cleaned!r}")
        if cleaned == '-':
            return 0.0
        if cleaned in (
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
            log.debug(f"Row {row}, Col {col}: Failed to convert {cleaned!r} to float, returning 0.0")
            return 0.0

    def _cell(self, row: int, col: int) -> float:
        row -= 1
        col -= 1
        return self.matrix[row][col] if col < len(self.matrix[row]) else 0.0

    async def _cached(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        if (val := await self.redis.get(key)):
            return json.loads(val)
        data = producer()
        if asyncio.iscoroutine(data):
            data = await data
        await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        return data

    def _map_month_key(self, ym: str) -> str:
        """Convert YYYY-MM to Russian month key used in month_subtotals."""
        month_map = {
            '11': 'нояб', '12': 'дек',
            '01': 'янв', '02': 'февр', '03': 'мар', '04': 'апр', '05': 'май'
        }
        try:
            year, month = ym.split('-')
            russian_month = month_map.get(month, month)
            return f"{year}-{russian_month}"
        except ValueError:
            return ym  # Return unchanged if format is invalid

    # ─── tree-roll для расходов ────────────────────────────────────
    def _roll(self, col: int, level: Literal["section", "category", "subcategory"], zero_suppress: bool = False) -> \
            Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for sec_code, sec in self.meta["expenses"].items():
            sec_sum = 0.0
            sec_node = {"name": sec["name"], "amount": 0.0, "cats": {}}
            for cat_code, cat in sec["cats"].items():
                cat_sum = 0.0
                cat_node = {"name": cat["name"], "amount": 0.0, "subs": {}}
                for sub_code, sub in cat["subs"].items():
                    val = self._cell(sub["row"], col)
                    if zero_suppress and val == 0.0:
                        continue
                    log.debug(f"Subcategory {sub_code} (row {sub['row']}, col {col}): value = {val}")
                    cat_sum += val
                    if level == "subcategory":
                        cat_node["subs"][sub_code] = {"name": sub["name"], "amount": val}
                if zero_suppress and cat_sum == 0.0:
                    continue
                cat_node["amount"] = cat_sum
                if level in ("category", "subcategory"):
                    sec_node["cats"][cat_code] = cat_node
                sec_sum += cat_sum
            if zero_suppress and sec_sum == 0.0:
                continue
            sec_node["amount"] = sec_sum
            if level == "section":
                sec_node.pop("cats")
            out[sec_code] = sec_node
        return out

    # ─── roll для кредиторов ───────────────────────────────────────
    def _roll_creditors(self, col: int, zero_suppress: bool = False) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for cred_code, cred in self.meta["creditors"].items():
            balance = self._cell(cred["base"] + 4, col)
            if zero_suppress and balance == 0.0:
                continue
            log.debug(f"Creditor {cred_code} (row {cred['base'] + 4}, col {col}): balance = {balance}")
            out[cred_code] = {"name": cred_code, "balance": balance}
        return out

    # ─── public API ────────────────────────────────────────────────
    async def day_breakdown(
            self,
            date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_month_summary: bool = False
    ) -> Dict[str, Any]:
        async def prod() -> Dict[str, Any]:
            col = self.meta["date_cols"].get(date)
            if col is None:
                raise ValueError(f"Date {date} not in metadata")

            # ─ income ─
            inc_total = 0.0
            inc_items = []
            for cat_code, cat in self.meta["income"]["cats"].items():
                v_cat = self._cell(cat["row"], col)
                if not zero_suppress or v_cat != 0.0:
                    if level != "section":
                        inc_items.append({"code": cat_code, "name": cat["name"], "amount": v_cat})
                inc_total += v_cat
                for sub_code, sub in cat["subs"].items():
                    v_sub = self._cell(sub["row"], col)
                    if not zero_suppress or v_sub != 0.0:
                        inc_items.append({"code": sub_code, "name": sub["name"], "amount": v_sub})
                    inc_total += v_sub

            # ─ expense ─
            exp_tree = self._roll(col, level, zero_suppress)
            exp_total = sum(s["amount"] for s in exp_tree.values())

            # ─ creditors ─
            cred_tree = self._roll_creditors(col, zero_suppress)
            cred_total = sum(c["balance"] for c in cred_tree.values())

            # ─ monthly progress ─
            ym = f"{date[6:10]}-{date[3:5]}"
            ym_russian = self._map_month_key(ym)
            ms = self.meta["month_subtotals"].get(ym_russian, {})
            month_inc = self._cell(5, ms["income"]) if "income" in ms else None
            month_exp = self._cell(17, ms["expense"]) if "expense" in ms else None

            result = {
                "date": date,
                "month": ym,
                "income": {
                    "total": inc_total,
                    "items": inc_items,
                    "month_progress": month_inc
                },
                "expense": {
                    "total": exp_total,
                    "tree": exp_tree,
                    "month_progress": month_exp
                },
                "creditors": {
                    "total": cred_total,
                    "items": cred_tree
                }
            }

            if include_month_summary:
                if ym_russian in self.meta["month_subtotals"]:
                    ms_ym = self.meta["month_subtotals"][ym_russian]
                    balance = self._cell(2, ms_ym["balance"]) if "balance" in ms_ym else None
                    free_cash = self._cell(3, ms_ym["balance"]) if "balance" in ms_ym else None
                    result["month_summary"] = {
                        "balance": balance,
                        "free_cash": free_cash,
                        "income_progress": self._cell(5, ms_ym["income"]) if "income" in ms_ym else None,
                        "expense_progress": self._cell(17, ms_ym["expense"]) if "expense" in ms_ym else None
                    }
                else:
                    log.warning(f"Month {ym_russian} not found in month_subtotals")

            return result

        return await self._cached(f"daydetail:{date}:{level}:{zero_suppress}:{include_month_summary}", 300, prod)

    async def get_month_summary(self, ym: str) -> Dict[str, Any]:
        ym_russian = self._map_month_key(ym)
        ms = self.meta["month_subtotals"].get(ym_russian)
        if not ms:
            raise ValueError(f"Month {ym_russian} not found in metadata")

        balance = self._cell(2, ms["balance"]) if "balance" in ms else None
        free_cash = self._cell(3, ms["balance"]) if "balance" in ms else None
        income_progress = self._cell(5, ms["income"]) if "income" in ms else None
        expense_progress = self._cell(17, ms["expense"]) if "expense" in ms else None

        return {
            "balance": balance,
            "free_cash": free_cash,
            "income_progress": income_progress,
            "expense_progress": expense_progress
        }

    async def period_expense_summary(
            self,
            start_date: str,
            end_date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False
    ) -> Dict[str, Any]:
        async def prod() -> Dict[str, Any]:
            start = datetime.strptime(start_date, "%d.%m.%Y")
            end = datetime.strptime(end_date, "%d.%m.%Y")
            log.debug(f"Parsed start_date: {start}, end_date: {end}")
            if start > end:
                raise ValueError("start_date must be before end_date")

            dates = []
            current = start
            while current <= end:
                date_str = current.strftime("%d.%m.%Y")
                if date_str in self.meta["date_cols"]:
                    dates.append(date_str)
                current += timedelta(days=1)

            breakdown = {}
            daily_expenses = {}
            totals = {
                "income": {"total": 0.0, "items": {}},
                "expense": {"total": 0.0, "tree": {}},
                "creditors": {"total": 0.0, "items": {}}
            }

            for date in dates:
                daily_data = await self.day_breakdown(date, level, zero_suppress)
                exp_total = daily_data["expense"]["total"]
                daily_expenses[date] = exp_total
                if zero_suppress and exp_total == 0.0 and daily_data["income"]["total"] == 0.0 and \
                        daily_data["creditors"]["total"] == 0.0:
                    continue
                breakdown[date] = daily_data

                # Aggregate income
                totals["income"]["total"] += daily_data["income"]["total"]
                for item in daily_data["income"]["items"]:
                    code = item["code"]
                    if code not in totals["income"]["items"]:
                        totals["income"]["items"][code] = {
                            "name": item["name"],
                            "amount": 0.0
                        }
                    totals["income"]["items"][code]["amount"] += item["amount"]

                # Aggregate expenses
                totals["expense"]["total"] += exp_total
                for sec_code, sec in daily_data["expense"]["tree"].items():
                    if sec_code not in totals["expense"]["tree"]:
                        totals["expense"]["tree"][sec_code] = {
                            "name": sec["name"],
                            "amount": 0.0,
                            "cats": {}
                        }
                    totals["expense"]["tree"][sec_code]["amount"] += sec["amount"]
                    for cat_code, cat in sec.get("cats", {}).items():
                        if cat_code not in totals["expense"]["tree"][sec_code]["cats"]:
                            totals["expense"]["tree"][sec_code]["cats"][cat_code] = {
                                "name": cat["name"],
                                "amount": 0.0,
                                "subs": {}
                            }
                        totals["expense"]["tree"][sec_code]["cats"][cat_code]["amount"] += cat["amount"]
                        for sub_code, sub in cat.get("subs", {}).items():
                            if sub_code not in totals["expense"]["tree"][sec_code]["cats"][cat_code]["subs"]:
                                totals["expense"]["tree"][sec_code]["cats"][cat_code]["subs"][sub_code] = {
                                    "name": sub["name"],
                                    "amount": 0.0
                                }
                            totals["expense"]["tree"][sec_code]["cats"][cat_code]["subs"][sub_code]["amount"] += sub[
                                "amount"]

                # Aggregate creditors
                totals["creditors"]["total"] += daily_data["creditors"]["total"]
                for cred_code, cred in daily_data["creditors"]["items"].items():
                    if cred_code not in totals["creditors"]["items"]:
                        totals["creditors"]["items"][cred_code] = {
                            "name": cred["name"],
                            "balance": 0.0
                        }
                    totals["creditors"]["items"][cred_code]["balance"] += cred["balance"]

            # Filter income items, keeping as dict
            if zero_suppress:
                totals["income"]["items"] = {
                    k: v for k, v in totals["income"]["items"].items()
                    if v["amount"] != 0.0
                }

            return {
                "period": f"{start_date} to {end_date}",
                "daily_expenses": daily_expenses,
                "breakdown": breakdown,
                "totals": totals
            }

        return await self._cached(f"periodsummary:{start_date}:{end_date}:{level}:{zero_suppress}", 300, prod)

    async def _month_sync(self, ym: str) -> Dict[str, float]:
        col = self.meta["month_cols"][ym]["balance"]
        bal = self._cell(2, col)
        free = self._cell(3, col)
        inc = sum(
            self._cell(cat["row"], col) +
            sum(self._cell(sub["row"], col) for sub in cat["subs"].values())
            for cat in self.meta["income"]["cats"].values()
        )
        exp = 0.0
        for sec in self.meta["expenses"].values():
            for cat in sec["cats"].values():
                for s in cat["subs"].values():
                    exp += self._cell(s["row"], col)
        return {"balance": bal, "free_cash": free, "income": inc, "expense": exp}

    async def month_totals(
            self,
            ym: str,
            include_balances: bool = False,
    ) -> Dict[str, float]:
        async def prod():
            ms = self.meta["month_subtotals"].get(ym)
            if ms:
                inc = self._cell(5, ms.get("income", 0))
                exp = self._cell(17, ms.get("expense", 0))
                bal = self._cell(2, ms["balance"]) if include_balances else None
                free = self._cell(3, ms["balance"]) if include_balances else None
            else:
                m = await self._month_sync(ym)
                inc, exp = m["income"], m["expense"]
                bal, free = m["balance"], m["free_cash"]
            d = {"income": inc, "expense": exp}
            if include_balances:
                d.update({"balance": bal, "free_cash": free})
            return d

        return await self._cached(f"month:{ym}:{include_balances}", 3600, prod)

    async def months_overview(self) -> Dict[str, Dict[str, float]]:
        async def prod():
            out = {}
            for ym in tqdm(self.meta["month_cols"], desc="Processing months overview"):
                out[ym] = await self.month_totals(ym)
            return out

        return await self._cached("months:overview:v2", 3600, prod)

    async def warm_cache(self):
        log.info("Warming up cache")
        if self.meta["date_cols"]:
            first = next(iter(self.meta["date_cols"]))
            log.info("Caching day breakdown for %s", first)
            await self.day_breakdown(first, "category")
        for ym in tqdm(list(self.meta["month_cols"])[:2], desc="Caching months"):
            log.info("Caching month totals for %s", ym)
            await self.month_totals(ym)


# ────────────────────────── CLI demo ─────────────────────────────
@timeit("CLI demo")
async def _demo():
    sn = SheetNumeric()
    await sn.warm_cache()
    date = "25.11.2024"
    print("▶ breakdown", date)
    import pprint
    try:
        pprint.pp(await sn.day_breakdown(date, "subcategory"), width=100)
    except ValueError as e:
        print(f"Error: {e}")
    ym = next(iter(sn.meta["month_cols"]))
    print("\n▶ month", ym, await sn.month_totals(ym))
    print("\n▶ months overview")
    pprint.pp(await sn.months_overview(), width=120)


if __name__ == "__main__":
    asyncio.run(_demo())
