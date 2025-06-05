# ---------------------------------------------------------------------------
# --- Imports ---------------------------------------------------------------
# ---------------------------------------------------------------------------

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Literal, Tuple

from tqdm import tqdm

from .meta import SheetMeta
from ..core.config import log
from ..core.connections import open_worksheet_sync, get_redis
from ..core.utils import to_a1, to_float

# ---------------------------------------------------------------------------
# --- Constants -------------------------------------------------------------
# ---------------------------------------------------------------------------

RAW_CACHE_KEY = "sheet:raw_data"
MATRIX_CACHE_KEY = "sheet:matrix"
RAW_TTL = 60 * 60  # 1 hour
MATRIX_TTL = 60 * 60  # 1 hour
GENERIC_TTL = 5 * 60  # Default TTL for _cached helper


# ---------------------------------------------------------------------------
# --- SheetNumeric ----------------------------------------------------------
# ---------------------------------------------------------------------------

class SheetNumeric:
    """Transforms raw sheet rows into numeric values and exposes analytics.

    The class converts raw spreadsheet data into a numeric matrix, where each
    cell represents a float value. The matrix is cached in Redis for performance,
    and analytics methods (e.g., day breakdown, month totals) use this matrix
    to compute summaries and breakdowns based on metadata from SheetMeta.

    Parameters
    ----------
    meta : SheetMeta | None
        Instance of SheetMeta that provides metadata (e.g., date_cols, expenses)
        to determine matrix structure and analytics calculations.
    """

    # ---------------------------------------------------------------------
    # --- Construction & Initialisation -----------------------------------
    # ---------------------------------------------------------------------

    def __init__(self, meta: SheetMeta | None = None) -> None:
        """Initialize SheetNumeric with optional metadata."""
        log.info("Initializing SheetNumeric")
        self.meta = meta
        self.redis = None  # Lazy-opened aioredis client
        self.rows: List[List[str]] = []
        self.notes: Dict[str, str] = {}
        self.matrix: List[List[float]] = []

    # ---------------------------------------------------------------------
    # --- Cache Management ------------------------------------------------
    # ---------------------------------------------------------------------

    async def _load_cached_raw_data(self) -> tuple[List[List[str]], Dict[str, str]] | None:
        """Load raw data from Redis cache if available."""
        if self.redis is None:
            self.redis = await get_redis()
        cached_data = await self.redis.get(RAW_CACHE_KEY)
        if cached_data:
            try:
                data = json.loads(cached_data)
                log.info("Loaded raw data from cache")
                return data["rows"], data["notes"]
            except json.JSONDecodeError:
                log.error("Failed to decode cached raw data")
                return None
        return None

    async def _save_raw_data_to_cache(self, rows: List[List[str]], notes: Dict[str, str]) -> None:
        """Save raw data to Redis cache."""
        if self.redis is None:
            self.redis = await get_redis()
        try:
            await self.redis.set(
                RAW_CACHE_KEY,
                json.dumps({"rows": rows, "notes": notes}, ensure_ascii=False),
                ex=RAW_TTL
            )
            log.info("Saved raw data to cache with key 'sheet:raw_data'")
        except Exception as e:
            log.error(f"Failed to save raw data to cache: {e}")

    async def _load_cached_matrix(self) -> List[List[float]] | None:
        """Load numeric matrix from Redis cache if available."""
        if self.redis is None:
            self.redis = await get_redis()
        cached_matrix = await self.redis.get(MATRIX_CACHE_KEY)
        if cached_matrix:
            try:
                log.info("Loaded matrix from cache")
                return json.loads(cached_matrix)
            except json.JSONDecodeError:
                log.error("Failed to decode cached matrix")
                return None
        return None

    async def _save_matrix_to_cache(self, matrix: List[List[float]]) -> None:
        """Save numeric matrix to Redis cache."""
        if self.redis is None:
            self.redis = await get_redis()
        try:
            await self.redis.set(
                MATRIX_CACHE_KEY,
                json.dumps(matrix, ensure_ascii=False),
                ex=MATRIX_TTL
            )
            log.info("Saved matrix to cache with key 'sheet:matrix'")
        except Exception as e:
            log.error(f"Failed to save matrix to cache: {e}")

    async def _cached(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        """Cache the result of a producer function with a given TTL."""
        if self.redis is None:
            self.redis = await get_redis()
        val = await self.redis.get(key)
        if val is not None:
            log.info(f"Cache hit for key {key}")
            return json.loads(val)
        data = producer()
        if asyncio.iscoroutine(data):
            data = await data
        try:
            await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
            log.info(f"Cache set for key {key} with TTL {ttl}")
        except Exception as e:
            log.error(f"Failed to cache data for key {key}: {e}")
        return data

    async def _get_comment(self, row: int, col: int) -> str:
        """Retrieve or cache a comment for a specific cell."""
        if self.redis is None:
            self.redis = await get_redis()
        cell_key = to_a1(row, col)
        key = f"comment:{cell_key}"
        comment = await self.redis.get(key)
        if comment is None:
            comment = self.notes.get(cell_key, "")
            await self.redis.set(key, comment, ex=GENERIC_TTL)
        return comment

    # ---------------------------------------------------------------------
    # --- Initialization & Matrix Building --------------------------------
    # ---------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the numeric matrix from raw data or cache."""
        log.info("Initializing SheetNumeric")
        cached_raw = await self._load_cached_raw_data()
        if cached_raw:
            self.rows, self.notes = cached_raw
            log.info("Using cached raw data")
        else:
            log.info("Loading data from Google Sheets")
            try:
                result = open_worksheet_sync()
                if not isinstance(result, tuple) or len(result) != 3:
                    raise ValueError("Expected tuple of length 3 from open_worksheet_sync")
                self.ws, self.rows, self.notes = result
                log.info(f"Loaded {len(self.rows)} rows, {len(self.notes)} notes")
                await self._save_raw_data_to_cache(self.rows, self.notes)
            except Exception as e:
                log.error(f"Failed to load data from Google Sheets: {e}")
                raise ValueError(f"Failed to load data from Google Sheets: {str(e)}")

        cached_matrix = await self._load_cached_matrix()
        if cached_matrix:
            self.matrix = cached_matrix
        else:
            log.info("Building matrix from rows")
            if self.meta is None or not self.meta.meta.get("date_cols"):
                raise ValueError("SheetMeta instance must provide date_cols to determine matrix size")
            max_cols = max(self.meta.meta["date_cols"].values(), default=0) + 1
            log.info(f"Determined max_cols: {max_cols}")

            self.matrix = []
            for row in tqdm(self.rows, desc="Converting to float matrix"):
                padded_row = row + [""] * (max_cols - len(row)) if row else [""] * max_cols
                row_values = [to_float(c) if c else 0.0 for c in padded_row]
                self.matrix.append(row_values)
            log.info(f"Matrix built with shape: ({len(self.matrix)}, {len(self.matrix[0]) if self.matrix else 0})")
            await self._save_matrix_to_cache(self.matrix)

        if self.meta is None:
            raise ValueError("SheetMeta instance must be provided to SheetNumeric")
        self.meta.rows = self.rows
        self.meta.notes = self.notes
        self.meta.col_b = [r[1].strip() if len(r) > 1 else "" for r in self.rows]
        self.meta.col_c = [r[2].strip() if len(r) > 2 else "" for r in self.rows]
        log.info("SheetNumeric initialization completed")

    # ---------------------------------------------------------------------
    # --- Cell Access & Computation ---------------------------------------
    # ---------------------------------------------------------------------

    def _cell(self, row: int, col: int) -> float:
        """Retrieve the numeric value of a cell from the matrix."""
        if not (0 <= row < len(self.matrix) and 0 <= col < len(self.matrix[0])):
            log.warning(
                f"Cell access out of bounds: row={row}, col={col}, matrix_size=({len(self.matrix)}, {len(self.matrix[0])})"
            )
            return 0.0

        raw_value = self.matrix[row][col]
        if raw_value is None:
            return 0.0

        if isinstance(raw_value, str) and raw_value.startswith("="):
            formula = raw_value.lstrip("=")
            parts = formula.split("+")
            total = 0.0
            for part in parts:
                part = part.strip()
                try:
                    total += float(part.replace(",", "."))
                except ValueError:
                    continue
            return total

        return float(raw_value) if raw_value else 0.0

    # ---------------------------------------------------------------------
    # --- Analytics Methods -----------------------------------------------
    # ---------------------------------------------------------------------

    async def _roll(self, col: int, level: Literal["section", "category", "subcategory"], zero_suppress: bool = False,
                    include_comments: bool = False) -> Dict[str, Dict[str, Any]]:
        """Roll up expense data by section, category, or subcategory."""
        col_idx = col
        out: Dict[str, Dict[str, Any]] = {}
        for sec_code, sec in self.meta.meta["expenses"].items():
            if not isinstance(sec, dict):
                continue
            sec_sum = 0.0
            sec_node = {"name": sec["name"], "amount": 0.0, "cats": {}}
            for cat_code, cat in sec["cats"].items():
                cat_sum = 0.0
                cat_node = {"name": cat["name"], "amount": 0.0, "subs": {}}
                for sub_code, sub in cat["subs"].items():
                    val = self._cell(sub["row"] - 1, col_idx)
                    comment = await self._get_comment(sub["row"], col_idx + 1) if include_comments else ""
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

    async def _roll_creditors(self, col: int, zero_suppress: bool = False, include_comments: bool = False) -> Dict[
        str, Dict[str, Any]]:
        """Roll up creditor balances."""
        col_idx = col
        out: Dict[str, Dict[str, Any]] = {}
        for cred_code, cred in self.meta.meta["creditors"].items():
            balance = self._cell(cred["base"] + 4 - 1, col_idx)
            comment = await self._get_comment(cred["base"] + 4, col_idx + 1) if include_comments else ""
            if zero_suppress and balance == 0.0:
                continue
            out[cred_code] = {"name": cred_code, "balance": balance, "comment": comment}
        return out

    async def _process_income_items(self, col: int, include_comments: bool, zero_suppress: bool = False,
                                    level: Literal["section", "category", "subcategory"] = "subcategory") -> Tuple[
        float, List[Dict[str, Any]]]:
        """Process income items for a given column."""
        col_idx = col
        inc_total = 0.0
        inc_items = []
        for cat_code, cat in self.meta.meta["income"].get("cats", {}).items():
            v_cat = self._cell(cat["row"] - 1, col_idx)
            comment = await self._get_comment(cat["row"], col_idx + 1) if include_comments else ""
            if not zero_suppress or v_cat != 0.0:
                if level != "section":
                    inc_items.append({"code": cat_code, "name": cat["name"], "amount": v_cat, "comment": comment})
            inc_total += v_cat
            for sub_code, sub in cat.get("subs", {}).items():
                v_sub = self._cell(sub["row"] - 1, col_idx)
                comment = await self._get_comment(sub["row"], col_idx + 1) if include_comments else ""
                if not zero_suppress or v_sub != 0.0:
                    inc_items.append({"code": sub_code, "name": sub["name"], "amount": v_sub, "comment": comment})
                inc_total += v_sub
        return inc_total, inc_items

    async def day_breakdown(
            self,
            date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_month_summary: bool = False,
            include_comments: bool = True
    ) -> Dict[str, Any]:
        """Generate a breakdown of financial data for a specific date."""

        async def prod() -> Dict[str, Any]:
            if not self.meta.meta["date_cols"]:
                raise ValueError("No date columns available in metadata. Please refresh data.")
            col = self.meta.meta["date_cols"].get(date)
            if col is None:
                raise ValueError(f"Date {date} not in metadata")
            col_idx = col - 1

            inc_total, inc_items = await self._process_income_items(col_idx, include_comments, zero_suppress, level)
            exp_tree = await self._roll(col_idx, level, zero_suppress, include_comments)
            total_row = self.meta.meta["expenses"].get("total_row", 0) - 1
            exp_total = self._cell(total_row, col_idx) if total_row >= 0 else 0.0
            cred_tree = await self._roll_creditors(col_idx, zero_suppress, include_comments)
            cred_total = sum(c["balance"] for c in cred_tree.values())

            ym = f"{date[6:10]}-{date[3:5]}"
            ms = self.meta.meta["month_cols"].get(ym, {})
            month_col = ms.get("balance", 0)
            month_col_idx = month_col - 1 if month_col else 0
            month_inc = self._cell(self.meta.meta["income"].get("total_row", 0) - 1,
                                   month_col_idx) if month_col else None
            month_exp = self._cell(self.meta.meta["expenses"].get("total_row", 0) - 1,
                                   month_col_idx) if month_col else None

            result = {
                "date": date,
                "month": ym,
                "income": {"total": inc_total, "items": inc_items, "month_progress": month_inc},
                "expense": {"total": exp_total, "tree": exp_tree, "month_progress": month_exp},
                "creditors": {"total": cred_total, "items": cred_tree}
            }

            if include_month_summary and ym in self.meta.meta["month_cols"]:
                ms_ym = self.meta.meta["month_cols"][ym]
                balance_col = ms_ym["balance"] - 1
                free_col = ms_ym["free"] - 1
                balance = self._cell(2 - 1, balance_col)
                free_cash = self._cell(3 - 1, free_col)
                result["month_summary"] = {
                    "balance": balance,
                    "free_cash": free_cash,
                    "income_progress": self._cell(self.meta.meta["income"].get("total_row", 0) - 1, balance_col),
                    "expense_progress": self._cell(self.meta.meta["expenses"].get("total_row", 0) - 1, balance_col)
                }

            return result

        return await self._cached(
            f"daydetail:{date}:{level}:{zero_suppress}:{include_month_summary}:{include_comments}", GENERIC_TTL, prod)

    async def get_month_summary(self, ym: str, include_comments: bool = True) -> Dict[str, Any]:
        """Generate a summary of financial data for a specific month."""
        if not self.meta.meta["month_cols"]:
            raise ValueError("No month columns available in metadata. Please refresh data.")
        ms = self.meta.meta["month_cols"].get(ym)
        if not ms:
            raise ValueError(f"Month {ym} not found in metadata")

        col = ms["balance"] - 1  # Adjust for 0-based indexing
        balance = self._cell(1, col)  # Row 2 (1-based) -> 1 (0-based)
        free_cash = self._cell(2, col)  # Row 3 (1-based) -> 2 (0-based)
        income_progress = self._cell(self.meta.meta["income"].get("total_row", 0) - 1,
                                     col)  # Adjust for 0-based indexing
        expense_progress = self._cell(self.meta.meta["expenses"].get("total_row", 0) - 1,
                                      col)  # Adjust for 0-based indexing

        inc_total, inc_items = await self._process_income_items(col, include_comments)
        exp_tree = await self._roll(col, "subcategory", zero_suppress=False, include_comments=include_comments)
        exp_total = sum(s["amount"] for s in exp_tree.values())

        exclude_creditors = [
            "ВЗЯЛИ В ДОЛГ :",
            "ВЕРНУЛИ ДОЛГ :",
            "СЭКОНОМИЛИ :",
            "ОСТАТОК - МЫ СКОЛЬКО ДОЛЖНЫ :"
        ]
        cred_tree = {}
        for cred_code, cred in self.meta.meta["creditors"].items():
            if cred_code in exclude_creditors:
                continue
            balance_val = self._cell(cred["base"] + 4 - 1, col)  # Adjust for 0-based indexing
            comment = await self._get_comment(cred["base"] + 4, col + 1) if include_comments else ""
            if balance_val != 0.0:
                cred_tree[cred_code] = {"name": cred_code, "balance": balance_val, "comment": comment}
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
        """Generate a summary of expenses over a date range."""

        async def prod() -> Dict[str, Any]:
            if not self.meta.meta["date_cols"]:
                raise ValueError("No date columns available in metadata. Please refresh data.")
            start = datetime.strptime(start_date, "%d.%m.%Y")
            end = datetime.strptime(end_date, "%d.%m.%Y")
            if start > end:
                raise ValueError("start_date must be before end_date")

            dates = []
            current = start
            while current <= end:
                date_str = current.strftime("%d.%m.%Y")
                if date_str in self.meta.meta["date_cols"]:
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
                daily_data = await self.day_breakdown(date, level, zero_suppress=zero_suppress,
                                                      include_comments=include_comments)
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

                totals["income"]["total"] += inc_total
                for item in daily_data["income"]["items"]:
                    code = item["code"]
                    if code not in totals["income"]["items"]:
                        totals["income"]["items"][code] = {
                            "name": item["name"],
                            "amount": 0.0
                        }
                    totals["income"]["items"][code]["amount"] += item["amount"]

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

                totals["creditors"]["total"] += cred_total
                for cred_code, cred in daily_data["creditors"]["items"].items():
                    if cred_code not in totals["creditors"]["items"]:
                        totals["creditors"]["items"][cred_code] = {
                            "name": cred["name"],
                            "balance": 0.0
                        }
                    totals["creditors"]["items"][cred_code]["balance"] += cred["balance"]

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
                                  GENERIC_TTL, prod)

    async def month_totals(
            self,
            ym: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_balances: bool = False,
    ) -> Dict[str, Any]:
        """Generate totals for a specific month."""

        async def prod() -> Dict[str, Any]:
            if not self.meta.meta["month_cols"]:
                raise ValueError("No month columns available in metadata. Please refresh data.")

            ms = self.meta.meta["month_cols"].get(ym)
            if not ms:
                raise ValueError(f"Month {ym} not found in metadata")

            col = ms["balance"] - 1  # Adjust for 0-based indexing

            # Balances
            balance = self._cell(1, col) if include_balances else None  # Row 2 (1-based) -> 1 (0-based)
            free_cash = self._cell(2, col) if include_balances else None  # Row 3 (1-based) -> 2 (0-based)

            # Income
            inc_total = self._cell(self.meta.meta["income"].get("total_row", 0) - 1, col)  # Adjust for 0-based indexing
            inc_items = []
            for cat_code, cat in self.meta.meta["income"].get("cats", {}).items():
                v_cat = self._cell(cat["row"] - 1, col)  # Adjust for 0-based indexing
                if not zero_suppress or v_cat != 0.0:
                    if level != "section":
                        inc_items.append({"code": cat_code, "name": cat["name"], "amount": v_cat})
                for sub_code, sub in cat.get("subs", {}).items():
                    v_sub = self._cell(sub["row"] - 1, col)  # Adjust for 0-based indexing
                    if not zero_suppress or v_sub != 0.0:
                        inc_items.append({"code": sub_code, "name": sub["name"], "amount": v_sub})

            # Expenses
            exp_tree = {}
            exp_total = self._cell(self.meta.meta["expenses"].get("total_row", 0) - 1,
                                   col)  # Adjust for 0-based indexing
            for sec_code, sec in self.meta.meta["expenses"].items():
                if not isinstance(sec, dict):  # Skip "total_row"
                    continue
                sec_sum = self._cell(sec.get("total_row", 0) - 1, col)  # Adjust for 0-based indexing
                sec_node = {"name": sec["name"], "amount": sec_sum, "cats": {}}
                for cat_code, cat in sec["cats"].items():
                    cat_sum = self._cell(cat["row"] - 1, col)  # Adjust for 0-based indexing
                    cat_node = {"name": cat["name"], "amount": cat_sum, "subs": {}}
                    for sub_code, sub in cat["subs"].items():
                        val = self._cell(sub["row"] - 1, col)  # Adjust for 0-based indexing
                        if zero_suppress and val == 0.0:
                            continue
                        if level == "subcategory":
                            cat_node["subs"][sub_code] = {"name": sub["name"], "amount": val}
                    if zero_suppress and cat_sum == 0.0:
                        continue
                    if level in ("category", "subcategory"):
                        sec_node["cats"][cat_code] = cat_node
                if zero_suppress and sec_sum == 0.0:
                    continue
                if level == "section":
                    sec_node.pop("cats")
                exp_tree[sec_code] = sec_node

            # Creditors
            cred_tree = {}
            cred_total = 0.0
            for cred_code, cred in self.meta.meta["creditors"].items():
                balance_val = self._cell(cred["base"] + 4 - 1, col)  # Adjust for 0-based indexing
                if zero_suppress and balance_val == 0.0:
                    continue
                cred_tree[cred_code] = {"name": cred_code, "balance": balance_val}
                cred_total += balance_val

            result = {
                "month": ym,
                "income": {
                    "total": inc_total,
                    "items": inc_items
                },
                "expense": {
                    "total": exp_total,
                    "tree": exp_tree
                },
                "creditors": {
                    "total": cred_total,
                    "items": cred_tree
                }
            }

            if include_balances:
                result["balance"] = balance
                result["free_cash"] = free_cash

            return result

        return await self._cached(f"month:{ym}:{level}:{zero_suppress}:{include_balances}", RAW_TTL, prod)

    async def months_overview(
            self,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_balances: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Generate an overview of all months."""

        async def prod():
            if not self.meta.meta["month_cols"]:
                raise ValueError("No month columns available in metadata. Please refresh data.")
            out = {}
            for ym in tqdm(self.meta.meta["month_cols"], desc="Processing months overview"):
                out[ym] = await self.month_totals(ym, level=level, zero_suppress=zero_suppress,
                                                  include_balances=include_balances)
            return out

        return await self._cached(f"months:overview:{level}:{zero_suppress}:{include_balances}", RAW_TTL, prod)

    async def warm_cache(self):
        """Pre-warm the cache with initial data."""
        log.info("Warming up cache")
        if self.meta.meta["date_cols"]:
            first = next(iter(self.meta.meta["date_cols"]))
            log.info("Caching day breakdown for %s", first)
            await self.day_breakdown(first, "category")
        else:
            log.warning("No date columns available for cache warming")
        for ym in tqdm(list(self.meta.meta["month_cols"])[:2], desc="Caching months"):
            log.info("Caching month totals for %s", ym)
            await self.month_totals(ym, level="category", zero_suppress=False, include_balances=False)
