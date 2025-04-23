# gateway/app/services/operations/sheets.py
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Literal

import gspread_asyncio
from gspread.exceptions import APIError

from ..analytics import SheetMeta, SheetNumeric
from ..core import log, get_async_worksheet, get_redis, COMMENT_TEMPLATES, to_a1, format_formula


class GoogleSheetsService:
    def __init__(self):
        self.redis = None
        self.task_queue = asyncio.Queue()
        self.meta = None
        self.numeric = None
        self._initialized = False
        self._worker_task = None
        self._init_lock = asyncio.Lock()

    async def initialize(self):
        async with self._init_lock:
            if not self._initialized:
                start_time = time.time()
                log.info("Initializing GoogleSheetsService")
                self.redis = await get_redis()
                try:
                    self.meta = SheetMeta()
                    self.meta.meta = await self.meta.build_meta()  # Загружаем данные и строим метаданные
                    self.numeric = SheetNumeric()
                    await self.numeric.initialize()
                    self._start_task_worker()
                    self._initialized = True
                    duration = (time.time() - start_time) * 1000
                    log.info(f"GoogleSheetsService initialized in {duration:.2f} ms")
                except Exception as e:
                    log.error(f"Failed to initialize GoogleSheetsService: {e}")
                    raise
            else:
                log.debug("GoogleSheetsService already initialized")

    async def refresh_data(self):
        """Принудительно обновляет данные, инвалидируя кэш."""
        async with self._init_lock:
            log.info("Refreshing data and invalidating cache")
            if self.redis is None:
                self.redis = await get_redis()
            keys = await self.redis.keys("sheet:*")
            keys += await self.redis.keys("daydetail:*")
            keys += await self.redis.keys("month:*")
            keys += await self.redis.keys("periodsummary:*")
            keys += await self.redis.keys("months:overview:*")
            if keys:
                await self.redis.delete(*keys)
                log.info(f"Invalidated cache keys: {keys}")
            else:
                log.debug("No cache keys found to invalidate")
            self._initialized = False
            await self.initialize()
            log.info("Data refresh completed")

    async def queue_task(self, operation: str, payload: Dict, user_id: str) -> str:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        task_id = str(uuid.uuid4())
        await self.redis.set(
            f"task:{task_id}",
            json.dumps({"status": "queued", "operation": operation, "user_id": user_id}),
            ex=3600
        )
        await self.task_queue.put((task_id, operation, payload, user_id))
        return task_id

    async def get_task_status(self, task_id: str) -> Dict:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        task = await self.redis.get(f"task:{task_id}")
        if not task:
            raise ValueError(f"Task {task_id} not found")
        return json.loads(task)

    def _start_task_worker(self):
        async def worker():
            ws = await get_async_worksheet()
            while True:
                task_id, operation, payload, user_id = await self.task_queue.get()
                try:
                    await self.redis.set(
                        f"task:{task_id}",
                        json.dumps({"status": "processing", "operation": operation, "user_id": user_id}),
                        ex=3600
                    )
                    if operation == "add_expense":
                        await self._add_expense(ws, payload)
                    elif operation == "remove_expense":
                        await self._remove_expense(ws, payload)
                    elif operation == "add_income":
                        await self._add_income(ws, payload)
                    elif operation == "remove_income":
                        await self._remove_income(ws, payload)
                    elif operation == "record_borrowing":
                        await self._record_borrowing(ws, payload)
                    elif operation == "remove_borrowing":
                        await self._remove_borrowing(ws, payload)
                    elif operation == "record_repayment":
                        await self._record_repayment(ws, payload)
                    elif operation == "remove_repayment":
                        await self._remove_repayment(ws, payload)
                    elif operation == "record_saving":
                        await self._record_saving(ws, payload)
                    elif operation == "remove_saving":
                        await self._remove_saving(ws, payload)
                    await self.redis.set(
                        f"task:{task_id}",
                        json.dumps({"status": "completed", "result": "Success", "error": "", "user_id": user_id}),
                        ex=3600
                    )
                    await self._invalidate_cache(payload)
                except Exception as e:
                    log.error(f"Task {task_id} failed: {str(e)}")
                    await self.redis.set(
                        f"task:{task_id}",
                        json.dumps({"status": "failed", "result": "Error", "error": str(e), "user_id": user_id}),
                        ex=3600
                    )
                finally:
                    self.task_queue.task_done()

        self._worker_task = asyncio.create_task(worker())
        log.info("Task worker started")

    async def _invalidate_cache(self, payload: Dict):
        if self.redis is None:
            self.redis = await get_redis()
        date = payload.get("date")
        keys = [
            "sheet:raw_data",
            "sheet:meta",
            "sheet:matrix"
        ]
        if date:
            ym = f"{date[6:10]}-{date[3:5]}"
            keys += await self.redis.keys(f"daydetail:{date}:*")
            keys += await self.redis.keys(f"month:{ym}:*")
            keys += await self.redis.keys(f"periodsummary:*{date}*")
            keys += await self.redis.keys("months:overview:*")
        if keys:
            await self.redis.delete(*keys)
            log.info(f"Invalidated cache keys: {keys}")
        # Обновляем meta и numeric
        self._initialized = False
        await self.initialize()

    async def _add_expense(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        date = payload["date"]
        chapter = payload["chapter"]
        category = payload["category"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        section = self.meta["expenses"].get(chapter)
        if not section:
            raise ValueError(f"Chapter {chapter} not found in metadata")
        cat = section["cats"].get(category)
        if not cat:
            raise ValueError(f"Category {category} not found in metadata")
        sub = cat["subs"].get(category)
        if not sub:
            raise ValueError(f"Subcategory {category} not found in metadata")

        cell = to_a1(sub["row"], col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "add")
            await ws.update([[new_formula]], cell, raw=False)
            if comment:
                note = f"{amount:.2f} ₽: Расход добавлен: {comment}"
                current_note = await ws.get_note(cell) or ""
                new_note = f"{current_note}\n{note}" if current_note else note
                await ws.update_note(cell, new_note)
                await self.redis.set(f"comment:{cell}", new_note, ex=3600)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _remove_expense(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        date = payload["date"]
        chapter = payload["chapter"]
        category = payload["category"]
        amount = payload["amount"]

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        section = self.meta["expenses"].get(chapter)
        if not section:
            raise ValueError(f"Chapter {chapter} not found in metadata")
        cat = section["cats"].get(category)
        if not cat:
            raise ValueError(f"Category {category} not found in metadata")
        sub = cat["subs"].get(category)
        if not sub:
            raise ValueError(f"Subcategory {category} not found in metadata")

        cell = to_a1(sub["row"], col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "remove")
            await ws.update([[new_formula]], cell, raw=False)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _add_income(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        date = payload["date"]
        category = payload["category"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        cat = self.meta["income"]["cats"].get(category)
        if not cat:
            raise ValueError(f"Category {category} not found in metadata")

        cell = to_a1(cat["row"], col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "add")
            await ws.update([[new_formula]], cell, raw=False)
            if comment:
                note = COMMENT_TEMPLATES["add_income"].format(amount=amount, comment=comment)
                current_note = await ws.get_note(cell) or ""
                new_note = f"{current_note}\n{note}" if current_note else note
                await ws.update_note(cell, new_note)
                await self.redis.set(f"comment:{cell}", new_note, ex=3600)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _remove_income(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        date = payload["date"]
        category = payload["category"]
        amount = payload["amount"]

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        cat = self.meta["income"]["cats"].get(category)
        if not cat:
            raise ValueError(f"Category {category} not found in metadata")

        cell = to_a1(cat["row"], col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "remove")
            await ws.update([[new_formula]], cell, raw=False)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _record_borrowing(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        creditor_name = payload["creditor_name"]
        date = payload["date"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta["creditors"].get(creditor_name)
        if not creditor:
            raise ValueError(f"Creditor {creditor_name} not found in metadata")

        cell = to_a1(creditor["base"], col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "add")
            await ws.update([[new_formula]], cell, raw=False)
            if comment:
                note = COMMENT_TEMPLATES["record_borrowing"].format(amount=amount, comment=comment)
                current_note = await ws.get_note(cell) or ""
                new_note = f"{current_note}\n{note}" if current_note else note
                await ws.update_note(cell, new_note)
                await self.redis.set(f"comment:{cell}", new_note, ex=3600)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _remove_borrowing(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        creditor_name = payload["creditor_name"]
        date = payload["date"]
        amount = payload["amount"]

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta["creditors"].get(creditor_name)
        if not creditor:
            raise ValueError(f"Creditor {creditor_name} not found in metadata")

        cell = to_a1(creditor["base"], col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "remove")
            await ws.update([[new_formula]], cell, raw=False)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _record_repayment(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        creditor_name = payload["creditor_name"]
        date = payload["date"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta["creditors"].get(creditor_name)
        if not creditor:
            raise ValueError(f"Creditor {creditor_name} not found in metadata")

        cell = to_a1(creditor["base"] + 1, col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "add")
            await ws.update([[new_formula]], cell, raw=False)
            if comment:
                note = COMMENT_TEMPLATES["record_repayment"].format(amount=amount, comment=comment)
                current_note = await ws.get_note(cell) or ""
                new_note = f"{current_note}\n{note}" if current_note else note
                await ws.update_note(cell, new_note)
                await self.redis.set(f"comment:{cell}", new_note, ex=3600)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _remove_repayment(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        creditor_name = payload["creditor_name"]
        date = payload["date"]
        amount = payload["amount"]

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta["creditors"].get(creditor_name)
        if not creditor:
            raise ValueError(f"Creditor {creditor_name} not found in metadata")

        cell = to_a1(creditor["base"] + 1, col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "remove")
            await ws.update([[new_formula]], cell, raw=False)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _record_saving(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        creditor_name = payload["creditor_name"]
        date = payload["date"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta["creditors"].get(creditor_name)
        if not creditor:
            raise ValueError(f"Creditor {creditor_name} not found in metadata")

        cell = to_a1(creditor["base"] + 2, col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "add")
            await ws.update([[new_formula]], cell, raw=False)
            if comment:
                note = COMMENT_TEMPLATES["record_saving"].format(amount=amount, comment=comment)
                current_note = await ws.get_note(cell) or ""
                new_note = f"{current_note}\n{note}" if current_note else note
                await ws.update_note(cell, new_note)
                await self.redis.set(f"comment:{cell}", new_note, ex=3600)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def _remove_saving(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        creditor_name = payload["creditor_name"]
        date = payload["date"]
        amount = payload["amount"]

        col = self.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta["creditors"].get(creditor_name)
        if not creditor:
            raise ValueError(f"Creditor {creditor_name} not found in metadata")

        cell = to_a1(creditor["base"] + 2, col)
        try:
            current = await ws.get(cell)
            current_val = current[0][0] if current and current[0] else ""
            new_formula = format_formula(amount, current_val, "remove")
            await ws.update([[new_formula]], cell, raw=False)
        except APIError as e:
            log.error(f"Failed to update cell {cell}: {e}")
            raise

    async def day_breakdown(
            self,
            date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_month_summary: bool = False,
            include_comments: bool = True
    ) -> Dict[str, Any]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.day_breakdown(date, level, zero_suppress, include_month_summary, include_comments)

    async def get_month_summary(self, ym: str, include_comments: bool = True) -> Dict[str, Any]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.get_month_summary(ym, include_comments)

    async def period_expense_summary(
            self,
            start_date: str,
            end_date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_comments: bool = True
    ) -> Dict[str, Any]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.period_expense_summary(start_date, end_date, level, zero_suppress, include_comments)

    async def month_totals(self, ym: str, include_balances: bool = False) -> Dict[str, float]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.month_totals(ym, include_balances)

    async def months_overview(self) -> Dict[str, Dict[str, float]]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.months_overview()
