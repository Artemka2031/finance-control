# gateway/app/services/analytics/meta.py
import asyncio
import json
import re
from typing import Dict, List, Callable, Any

from ..core import log
from ..core.connections import open_worksheet_sync, get_redis


class SheetMeta:
    def __init__(self):
        log.info("Initializing SheetMeta")
        self.redis = None
        self.rows = []
        self.notes = {}
        self.col_b = []
        self.col_c = []
        self.meta = {
            "income": {},
            "expenses": {},
            "creditors": {},
            "date_cols": {},
            "month_cols": {},
            "balances": {},
            "month_subtotals": {}
        }

    async def _load_cached_raw_data(self) -> tuple[List[List[str]], Dict[str, str]] | None:
        """Проверяет и загружает сырые данные из кэша."""
        if self.redis is None:
            self.redis = await get_redis()
        cached_data = await self.redis.get("sheet:raw_data")
        if cached_data:
            try:
                log.debug("Attempting to load raw data from cache")
                data = json.loads(cached_data)
                log.info("Loaded raw data from cache")
                return data["rows"], data["notes"]
            except json.JSONDecodeError as e:
                log.error(f"Failed to decode cached raw data: {e}")
                return None
        log.debug("No cached raw data found")
        return None

    async def _save_raw_data_to_cache(self, rows: List[List[str]], notes: Dict[str, str]) -> None:
        """Сохраняет сырые данные в кэш."""
        if self.redis is None:
            self.redis = await get_redis()
        try:
            log.debug(f"Saving raw data to cache: rows={len(rows)}, notes={len(notes)}")
            await self.redis.set(
                "sheet:raw_data",
                json.dumps({"rows": rows, "notes": notes}, ensure_ascii=False),
                ex=3600
            )
            log.info("Saved raw data to cache with key 'sheet:raw_data'")
        except Exception as e:
            log.error(f"Failed to save raw data to cache: {e}")

    async def _cached(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        """Кэширует результат выполнения producer."""
        if self.redis is None:
            self.redis = await get_redis()
        val = await self.redis.get(key)
        if val is not None:
            log.debug(f"Cache hit for key {key}")
            return json.loads(val)
        log.debug(f"Cache miss for key {key}, executing producer")
        data = producer()
        if asyncio.iscoroutine(data):
            data = await data
        try:
            await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
            log.debug(f"Cache set for key {key} with TTL {ttl}")
        except Exception as e:
            log.error(f"Failed to cache data for key {key}: {e}")
        return data

    def _index_in_col_b(self, needle: str) -> int:
        try:
            return self.col_b.index(needle) + 1
        except ValueError:
            log.debug(f"'{needle}' not found in column B")
            return -1

    def _get_row(self, row: int, col: int) -> str:
        row -= 1
        val = (
            self.rows[row][col - 1].strip()
            if row < len(self.rows) and col <= len(self.rows[row])
            else ""
        )
        log.debug(f"Got value '{val}' at row {row + 1}, col {col}")
        return val

    def _month_to_num(self, month_abbr: str) -> str:
        month_map = {
            'янв': '01', 'февр': '02', 'мар': '03', 'апр': '04', 'май': '05',
            'июн': '06', 'июл': '07', 'авг': '08', 'сент': '09', 'окт': '10',
            'нояб': '11', 'дек': '12'
        }
        return month_map.get(month_abbr.lower()[:3], '00')

    def _scan_balances(self) -> None:
        self.meta["balances"] = {
            "free": {"row": 3, "col": 4},
            "total": {"row": 3, "col": 5}
        }
        log.debug(f"Balances set: {self.meta['balances']}")

    def _scan_date_columns(self) -> bool:
        date_row = self._index_in_col_b("П")
        if date_row == -1:
            date_row = self._index_in_col_b("Р0")
        if date_row == -1:
            log.warning("Date row ('П' or 'Р0') not found in column B")
            log.debug(f"First 10 elements of col_b: {self.col_b[:10]}")
            return False

        log.info(f"Date row found at index {date_row}")
        row = self.rows[date_row - 1]
        current_month = None
        last_day_col = None
        month_days = {}  # Храним дни для каждого месяца
        month_end_dates = {
            "01": 31, "02": 28, "03": 31, "04": 30, "05": 31, "06": 30,
            "07": 31, "08": 31, "09": 30, "10": 31, "11": 30, "12": 31
        }

        # Проходим по столбцам, ищем даты
        for col in range(6, len(row)):
            cell = row[col].strip()
            if re.match(r"^\d{2}\.\d{2}\.\d{4}$", cell):
                parts = cell.split(".")
                if len(parts) == 3:
                    dd, mm, yyyy = parts
                    ym = f"{yyyy}-{mm.zfill(2)}"
                    self.meta["date_cols"][cell] = col + 1
                    log.debug(f"Added date {cell} to date_cols at column {col + 1}")

                    # Если месяц сменился, фиксируем итоговый столбец для предыдущего месяца
                    if current_month != ym:
                        if current_month and last_day_col:
                            expected_days = month_end_dates[current_month.split('-')[1]]
                            last_day = max(month_days[current_month])
                            if int(last_day) != expected_days:
                                log.warning(
                                    f"Последний день месяца {current_month} — {last_day}, ожидалось {expected_days}")
                            else:
                                # Следующий столбец после последней даты — итоговый
                                self.meta["month_cols"][current_month] = {"balance": last_day_col + 2,
                                                                          "free": last_day_col + 2}
                                log.info(f"Set month {current_month} with balance column {last_day_col + 2}")
                        current_month = ym
                        month_days[ym] = []
                    month_days[ym].append(dd)
                    last_day_col = col

        # Фиксируем итоговый столбец для последнего месяца
        if current_month and last_day_col:
            expected_days = month_end_dates[current_month.split('-')[1]]
            last_day = max(month_days[current_month])
            if int(last_day) != expected_days:
                log.warning(f"Последний день месяца {current_month} — {last_day}, ожидалось {expected_days}")
            else:
                self.meta["month_cols"][current_month] = {"balance": last_day_col + 2, "free": last_day_col + 2}
                log.info(f"Set final month {current_month} with balance column {last_day_col + 2}")

        # Сортируем month_cols по ключам
        self.meta["month_cols"] = dict(sorted(self.meta["month_cols"].items()))
        log.info(f"Date columns: {list(self.meta['date_cols'].keys())}")
        log.info(f"Month columns: {self.meta['month_cols']}")
        if not self.meta["date_cols"]:
            log.warning("No valid dates found in date row")
            return False
        return True

    def _scan_income_tree(self) -> None:
        root = self._index_in_col_b("П")
        if root == -1:
            log.debug("Income root 'П' not found")
            self.meta["income"] = {"cats": {}, "total_row": -1}
            return

        cats = {}
        cat_code = ""
        log.info(f"Scanning income tree from row {root}")
        for i in range(root, len(self.col_b)):
            code = self.col_b[i]
            if code.startswith("Итого"):
                self.meta["income"] = {"cats": cats, "total_row": i + 1}
                break
            if code and "." not in code:
                cats[code] = {"name": self.col_c[i], "row": i + 1, "subs": {}}
                cat_code = code
            elif cat_code and code.startswith(f"{cat_code}."):
                cats[cat_code]["subs"][code] = {"name": self.col_c[i], "row": i + 1}
        else:
            self.meta["income"] = {"cats": cats, "total_row": root}
        log.info(f"Income categories: {list(cats.keys())}")

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
                if code.startswith("Итого по всем разделам:"):
                    self.meta["expenses"]["total_row"] = j + 1
                    log.info(f"Found 'Итого по всем разделам:' at row {j + 1}")
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
            last_row = last_section.get("row_end", last_section["row"])
            # Проверяем строки ниже последней секции
            for k in range(last_row, min(last_row + 3, len(self.col_b))):
                if self.col_b[k].startswith("Итого по всем разделам:"):
                    self.meta["expenses"]["total_row"] = k + 1
                    log.info(f"Found 'Итого по всем разделам:' at row {k + 1} after last section")
                    break
            else:
                self.meta["expenses"]["total_row"] = last_row + 2
                log.warning(f"'Итого по всем разделам:' not found, setting total_row to {last_row + 2}")
        log.info(f"Expense sections: {list(expenses.keys())}")
        if "total_row" in self.meta["expenses"]:
            log.info(f"Total row for expenses: {self.meta['expenses']['total_row']}")

    def _scan_creditors(self) -> None:
        codes = self.col_b
        try:
            start = codes.index("К") + 1
            end = codes.index("Итоговая сумма экономии :")
            if end < start:
                end = len(codes)
        except ValueError:
            log.debug("Creditors 'К' or 'Итоговая сумма экономии :' not found")
            self.meta["creditors"] = {}
            return
        exclude_creditors = [
            "ВЗЯЛИ В ДОЛГ :",
            "ВЕРНУЛИ ДОЛГ :",
            "СЭКОНОМИЛИ :",
            "ОСТАТОК - МЫ СКОЛЬКО ДОЛЖНЫ :"
        ]
        creditors = {}
        for i in range(start, end, 5):
            name = self.col_c[i].strip()
            if name and name not in exclude_creditors:
                creditors[name] = {"base": i + 1}
        self.meta["creditors"] = creditors
        log.info(f"Creditors: {list(creditors.keys())}")

    async def build_meta(self) -> Dict:
        log.debug("Starting build_meta")

        async def produce_meta():
            log.info("Building metadata")
            self._scan_balances()
            if not self._scan_date_columns():
                log.warning("Failed to scan date columns, continuing with partial metadata")
            self._scan_income_tree()
            self._scan_expense_tree()
            self._scan_creditors()
            log.info("Metadata building completed")
            return self.meta

        # Проверяем кэш сырых данных
        cached_raw = await self._load_cached_raw_data()
        if cached_raw:
            log.debug(f"Using cached raw data: rows={len(cached_raw[0])}, notes={len(cached_raw[1])}")
            self.rows, self.notes = cached_raw
        else:
            # Загружаем данные из Google Sheets
            log.debug("Loading data from Google Sheets")
            try:
                result = open_worksheet_sync()
                if not isinstance(result, tuple) or len(result) != 3:
                    raise ValueError(f"Expected tuple of length 3, got {type(result)}")
                self.ws, self.rows, self.notes = result
                log.info(f"Loaded {len(self.rows)} rows, {len(self.notes)} notes")
                await self._save_raw_data_to_cache(self.rows, self.notes)
            except Exception as e:
                log.error(f"Failed to load data from Google Sheets: {e}")
                raise ValueError(f"Failed to load data from Google Sheets: {str(e)}")

        # Инициализируем col_b и col_c
        self.col_b = [r[1].strip() if len(r) > 1 else "" for r in self.rows]
        self.col_c = [r[2].strip() if len(r) > 2 else "" for r in self.rows]
        log.debug(f"Initialized col_b with {len(self.col_b)} elements, col_c with {len(self.col_c)} elements")

        # Проверяем кэш метаданных
        self.meta = await self._cached("sheet:meta", 86400, produce_meta)
        log.debug("build_meta completed")
        return self.meta
