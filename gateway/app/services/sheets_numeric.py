from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Literal, Tuple

import redis.asyncio as aioredis
from dotenv import load_dotenv
from tqdm import tqdm

from .gs_utils import open_worksheet, timeit, to_a1
from .sheets_meta import SheetMeta

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv(".env")
log = logging.getLogger(__name__)


# ────────────────────────── service class ──────────────────────────
class SheetNumeric:
    def __init__(self) -> None:
        self.ws, self.rows, self.notes = open_worksheet()
        log.info("Loaded %d rows from Google Sheets", len(self.rows))
        self.meta = SheetMeta(self.rows).build_meta()
        log.info("Building float matrix for %d rows", len(self.rows))
        self.matrix: List[List[float]] = []
        for row_idx, row in enumerate(tqdm(self.rows, desc="Converting to float matrix")):
            row_values = [SheetNumeric._to_float(c) for c in row]
            self.matrix.append(row_values)
        self.redis = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            encoding="utf-8",
            decode_responses=True,
        )
        self.notes: Dict[str, str] = self.notes  # Примечания из Google Sheets

    # ─── helpers ───────────────────────────────────────────────────
    @staticmethod
    def _to_float(raw: str) -> float:
        if not raw or raw.strip() == '-':
            return 0.0
        cleaned = (
            raw.replace("\xa0", "")
            .replace(" ", "")
            .replace(",", ".")
            .replace("₽", "")
            .strip()
        )
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
            return 0.0

    def _cell(self, row: int, col: int) -> float:
        row -= 1
        col -= 1
        return self.matrix[row][col] if col < len(self.matrix[row]) else 0.0

    async def _cached(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        if val := await self.redis.get(key):
            return json.loads(val)
        data = producer()
        if asyncio.iscoroutine(data):
            data = await data
        await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        return data

    async def _get_comment(self, row: int, col: int) -> str:
        # Формируем ключ в формате A1
        cell_key = to_a1(row, col)
        key = f"comment:{cell_key}"
        comment = await self.redis.get(key)
        if comment is None:
            comment = self.notes.get(cell_key, "")
            log.debug(f"Fetching comment for {cell_key} (row={row}, col={col}): {comment!r}")
            await self.redis.set(key, comment, ex=3600)
        return comment

    # ─── tree-roll для расходов ────────────────────────────────────
    async def _roll(self, col: int, level: Literal["section", "category", "subcategory"], zero_suppress: bool = False,
                    include_comments: bool = False) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for sec_code, sec in self.meta["expenses"].items():
            sec_sum = 0.0
            sec_node = {"name": sec["name"], "amount": 0.0, "cats": {}}
            for cat_code, cat in sec["cats"].items():
                cat_sum = 0.0
                cat_node = {"name": cat["name"], "amount": 0.0, "subs": {}}
                for sub_code, sub in cat["subs"].items():
                    val = self._cell(sub["row"], col)
                    comment = await self._get_comment(sub["row"], col) if include_comments else ""
                    if zero_suppress and val == 0.0:
                        continue
                    cat_sum += val
                    if level == "subcategory":
                        cat_node["subs"][sub_code] = {"name": sub["name"], "amount": val, "comment": comment}
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
    async def _roll_creditors(self, col: int, zero_suppress: bool = False, include_comments: bool = False) -> Dict[
        str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for cred_code, cred in self.meta["creditors"].items():
            balance = self._cell(cred["base"] + 4, col)
            comment = await self._get_comment(cred["base"] + 4, col) if include_comments else ""
            if zero_suppress and balance == 0.0:
                continue
            out[cred_code] = {"name": cred_code, "balance": balance, "comment": comment}
        return out

    async def _process_income_items(self, col: int, include_comments: bool, zero_suppress: bool = False,
                                    level: Literal["section", "category", "subcategory"] = "subcategory") -> Tuple[
        float, List[Dict[str, Any]]]:
        inc_total = 0.0
        inc_items = []
        for cat_code, cat in self.meta["income"].get("cats", {}).items():
            v_cat = self._cell(cat["row"], col)
            comment = await self._get_comment(cat["row"], col) if include_comments else ""
            if not zero_suppress or v_cat != 0.0:
                if level != "section":
                    inc_items.append({"code": cat_code, "name": cat["name"], "amount": v_cat, "comment": comment})
            inc_total += v_cat
            for sub_code, sub in cat.get("subs", {}).items():
                v_sub = self._cell(sub["row"], col)
                comment = await self._get_comment(sub["row"], col) if include_comments else ""
                if not zero_suppress or v_sub != 0.0:
                    inc_items.append({"code": sub_code, "name": sub["name"], "amount": v_sub, "comment": comment})
                inc_total += v_sub
        return inc_total, inc_items

    # ─── public API ────────────────────────────────────────────────
    async def day_breakdown(
            self,
            date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_month_summary: bool = False,
            include_comments: bool = True
    ) -> Dict[str, Any]:
        async def prod() -> Dict[str, Any]:
            col = self.meta["date_cols"].get(date)
            if col is None:
                raise ValueError(f"Date {date} not in metadata")

            # ─ income ─
            inc_total, inc_items = await self._process_income_items(col, include_comments, zero_suppress, level)

            # ─ expense ─
            exp_tree = await self._roll(col, level, zero_suppress, include_comments)
            exp_total = sum(s["amount"] for s in exp_tree.values())

            # ─ creditors ─
            cred_tree = await self._roll_creditors(col, zero_suppress, include_comments)
            cred_total = sum(c["balance"] for c in cred_tree.values())

            # ─ monthly progress ─
            ym = f"{date[6:10]}-{date[3:5]}"
            ms = self.meta["month_cols"].get(ym, {})
            month_col = ms.get("balance", 0)
            month_inc = self._cell(5, month_col) if month_col else None
            month_exp = self._cell(17, month_col) if month_col else None

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
                if ym in self.meta["month_cols"]:
                    ms_ym = self.meta["month_cols"][ym]
                    balance = self._cell(2, ms_ym["balance"])
                    free_cash = self._cell(3, ms_ym["balance"])
                    result["month_summary"] = {
                        "balance": balance,
                        "free_cash": free_cash,
                        "income_progress": self._cell(5, ms_ym["balance"]),
                        "expense_progress": self._cell(17, ms_ym["balance"])
                    }
                else:
                    log.warning(f"Month {ym} not found in month_cols")

            return result

        return await self._cached(
            f"daydetail:{date}:{level}:{zero_suppress}:{include_month_summary}:{include_comments}", 300, prod)

    async def get_month_summary(self, ym: str, include_comments: bool = True) -> Dict[str, Any]:
        ms = self.meta["month_cols"].get(ym)
        if not ms:
            raise ValueError(f"Month {ym} not found in metadata")

        col = ms["balance"]
        balance = self._cell(2, col)
        free_cash = self._cell(3, col)
        income_progress = self._cell(5, col)
        expense_progress = self._cell(17, col)

        # Получаем детализированные доходы с комментариями
        inc_total, inc_items = await self._process_income_items(col, include_comments)

        # Получаем детализированные расходы с комментариями
        exp_tree = await self._roll(col, "subcategory", zero_suppress=False, include_comments=include_comments)
        exp_total = sum(s["amount"] for s in exp_tree.values())

        # Получаем кредиторов с комментариями, исключая служебные поля
        exclude_creditors = [
            "ВЗЯЛИ В ДОЛГ :",
            "ВЕРНУЛИ ДОЛГ :",
            "СЭКОНОМИЛИ :",
            "ОСТАТОК - МЫ СКОЛЬКО ДОЛЖНЫ :"
        ]
        cred_tree = {}
        for cred_code, cred in self.meta["creditors"].items():
            if cred_code in exclude_creditors:
                continue
            balance = self._cell(cred["base"] + 4, col)
            comment = await self._get_comment(cred["base"] + 4, col) if include_comments else ""
            if balance != 0.0:
                cred_tree[cred_code] = {"name": cred_code, "balance": balance, "comment": comment}
        cred_total = sum(c["balance"] for c in cred_tree.values())

        return {
            "month": ym,
            "balance": balance,
            "free_cash": free_cash,
            "income": {
                "total": inc_total,
                "items": inc_items,
                "progress": income_progress
            },
            "expense": {
                "total": exp_total,
                "tree": exp_tree,
                "progress": expense_progress
            },
            "creditors": {
                "total": cred_total,
                "items": cred_tree
            }
        }

    async def period_expense_summary(
            self,
            start_date: str,
            end_date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_comments: bool = True
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
            daily_summary = {}
            totals = {
                "income": {"total": 0.0, "items": {}},
                "expense": {"total": 0.0, "tree": {}},
                "creditors": {"total": 0.0, "items": {}}
            }

            for date in dates:
                daily_data = await self.day_breakdown(date, level, zero_suppress, include_comments=include_comments)
                inc_total = daily_data["income"]["total"]
                exp_total = daily_data["expense"]["total"]
                cred_total = daily_data["creditors"]["total"]
                daily_summary[date] = {
                    "income": inc_total,
                    "expense": exp_total,
                    "creditors": cred_total
                }
                if zero_suppress and inc_total == 0.0 and exp_total == 0.0 and cred_total == 0.0:
                    continue
                breakdown[date] = daily_data

                # Агрегируем доходы
                totals["income"]["total"] += inc_total
                for item in daily_data["income"]["items"]:
                    code = item["code"]
                    if code not in totals["income"]["items"]:
                        totals["income"]["items"][code] = {
                            "name": item["name"],
                            "amount": 0.0
                        }
                    totals["income"]["items"][code]["amount"] += item["amount"]

                # Агрегируем расходы
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

                # Агрегируем кредиторов
                totals["creditors"]["total"] += cred_total
                for cred_code, cred in daily_data["creditors"]["items"].items():
                    if cred_code not in totals["creditors"]["items"]:
                        totals["creditors"]["items"][cred_code] = {
                            "name": cred["name"],
                            "balance": 0.0
                        }
                    totals["creditors"]["items"][cred_code]["balance"] += cred["balance"]

            # Фильтруем доходы, если нужно
            if zero_suppress:
                totals["income"]["items"] = {
                    k: v for k, v in totals["income"]["items"].items()
                    if v["amount"] != 0.0
                }

            return {
                "period": f"{start_date} to {end_date}",
                "daily_summary": daily_summary,
                "breakdown": breakdown,
                "totals": totals
            }

        return await self._cached(f"periodsummary:{start_date}:{end_date}:{level}:{zero_suppress}:{include_comments}",
                                  300, prod)

    async def _month_sync(self, ym: str) -> Dict[str, float]:
        col = self.meta["month_cols"][ym]["balance"]
        bal = self._cell(2, col)
        free = self._cell(3, col)
        inc = sum(
            self._cell(cat["row"], col) +
            sum(self._cell(sub["row"], col) for sub in cat["subs"].values())
            for cat in self.meta["income"].get("cats", {}).values()
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
