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
    _instance = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls) -> "GoogleSheetsService":
        async with cls._lock:
            if cls._instance is None:
                log.info("Creating new GoogleSheetsService instance")
                cls._instance = cls()
                await cls._instance.initialize()
            else:
                log.debug(f"Returning existing GoogleSheetsService instance: {id(cls._instance)}")
            return cls._instance

    def __init__(self):
        if GoogleSheetsService._instance is not None:
            raise RuntimeError("Use GoogleSheetsService.get_instance() to access the singleton instance")
        log.debug(f"Initializing new GoogleSheetsService instance: {id(self)}")
        self.redis = None
        self.task_queue = asyncio.Queue()
        self.meta = None
        self.numeric = None
        self._initialized = False
        self._worker_task = None
        self._init_lock = asyncio.Lock()

    async def initialize(self):
        log.warning(f"Initializing GoogleSheetsService, self._init_lock: {self._init_lock}, instance: {id(self)}")
        async with self._init_lock:
            log.debug(f"Acquired _init_lock for initialize, instance: {id(self)}")
            if not self._initialized:
                start_time = time.time()
                log.info("Initializing GoogleSheetsService")
                if self.redis is None:
                    try:
                        self.redis = await get_redis()
                        log.debug("Successfully connected to Redis")
                    except Exception as e:
                        log.error(f"Failed to connect to Redis: {str(e)}", exc_info=True)
                        raise
                redis_keys_before = await self.redis.keys("*:*")
                log.info(f"Cache keys before initialization: {redis_keys_before}")
                try:
                    log.debug("Starting SheetMeta initialization")
                    if not isinstance(self.meta, SheetMeta):
                        self.meta = SheetMeta()
                    try:
                        self.meta.meta = await asyncio.wait_for(
                            self.meta.build_meta(),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        log.error("Timeout while building SheetMeta")
                        raise
                    log.debug("SheetMeta initialization completed")

                    log.debug("Starting SheetNumeric initialization")
                    if self.numeric is None:
                        self.numeric = SheetNumeric(meta=self.meta)
                    try:
                        await asyncio.wait_for(
                            self.numeric.initialize(),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        log.error("Timeout while initializing SheetNumeric")
                        raise
                    log.debug("SheetNumeric initialization completed")

                    self._start_task_worker()
                    self._initialized = True
                    duration = (time.time() - start_time) * 1000
                    log.info(f"GoogleSheetsService initialized in {duration:.2f} ms")

                    redis_keys_after = await self.redis.keys("sheet:*")
                    log.info(f"Cache keys after initialization: {redis_keys_after}")
                except (Exception, BaseException) as e:
                    log.error(f"Failed to initialize GoogleSheetsService: {str(e)}", exc_info=True)
                    redis_keys_failed = await self.redis.keys("*:*")
                    log.info(f"Cache keys after failed initialization: {redis_keys_failed}")
                    raise
            else:
                log.debug("GoogleSheetsService already initialized")
            log.debug(f"Releasing _init_lock for initialize, instance: {id(self)}")

    async def refresh_cache(self):
        log.info(f"Refreshing cache and data, instance: {id(self)}")
        async with self._init_lock:
            log.debug(f"Acquired _init_lock for refresh_cache, instance: {id(self)}")
            if not self._initialized:
                log.error("Service not initialized, cannot refresh cache")
                raise RuntimeError("GoogleSheetsService not initialized")
            if self.redis is None:
                try:
                    self.redis = await get_redis()
                    log.debug("Successfully connected to Redis")
                except Exception as e:
                    log.error(f"Failed to connect to Redis: {str(e)}", exc_info=True)
                    raise
            try:
                all_keys_before = await self.redis.keys("*:*")
                log.info(f"All cache keys before invalidation: {all_keys_before}")

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

                all_keys_after_invalidation = await self.redis.keys("*:*")
                log.info(f"All cache keys after invalidation: {all_keys_after_invalidation}")

                log.debug("Refreshing SheetMeta data")
                try:
                    self.meta.meta = await asyncio.wait_for(
                        self.meta.build_meta(),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    log.error("Timeout while refreshing SheetMeta")
                    raise

                log.debug("Refreshing SheetNumeric data")
                try:
                    await asyncio.wait_for(
                        self.numeric.initialize(),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    log.error("Timeout while refreshing SheetNumeric")
                    raise

                log.info("Cache and data refresh completed")

                redis_keys = await self.redis.keys("sheet:*")
                all_keys_after_refresh = await self.redis.keys("*:*")
                log.info(f"Cache keys after refresh (sheet:*): {redis_keys}")
                log.info(f"All cache keys after refresh: {all_keys_after_refresh}")
            except (Exception, BaseException) as e:
                log.error(f"Failed to refresh cache: {str(e)}", exc_info=True)
                redis_keys_failed = await self.redis.keys("*:*")
                log.info(f"Cache keys after failed refresh: {redis_keys_failed}")
                raise
            log.debug(f"Releasing _init_lock for refresh_cache, instance: {id(self)}")

    async def refresh_data(self):
        log.warning("refresh_data is deprecated, use refresh_cache instead")
        await self.refresh_cache()

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
        log.debug(f"Invalidating cache, instance: {id(self)}")
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
        log.debug(f"Calling refresh_cache from _invalidate_cache, instance: {id(self)}")
        await self.refresh_cache()

    async def _add_expense(self, ws: gspread_asyncio.AsyncioGspreadWorksheet, payload: Dict):
        date = payload["date"]
        sec_code = payload["sec_code"]
        cat_code = payload["cat_code"]
        sub_code = payload["sub_code"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        section = self.meta.meta["expenses"].get(sec_code)
        if not section:
            raise ValueError(f"Section {sec_code} not found in metadata")
        cat = section["cats"].get(cat_code)
        if not cat:
            raise ValueError(f"Category {cat_code} not found in metadata")
        sub = cat["subs"].get(sub_code)
        if not sub:
            raise ValueError(f"Subcategory {sub_code} not found in metadata")

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
        sec_code = payload["sec_code"]
        cat_code = payload["cat_code"]
        sub_code = payload["sub_code"]
        amount = payload["amount"]

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        section = self.meta.meta["expenses"].get(sec_code)
        if not section:
            raise ValueError(f"Section {sec_code} not found in metadata")
        cat = section["cats"].get(cat_code)
        if not cat:
            raise ValueError(f"Category {cat_code} not found in metadata")
        sub = cat["subs"].get(sub_code)
        if not sub:
            raise ValueError(f"Subcategory {sub_code} not found in metadata")

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
        cat_code = payload["cat_code"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        cat = self.meta.meta["income"]["cats"].get(cat_code)
        if not cat:
            raise ValueError(f"Category {cat_code} not found in metadata")

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
        cat_code = payload["cat_code"]
        amount = payload["amount"]

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        cat = self.meta.meta["income"]["cats"].get(cat_code)
        if not cat:
            raise ValueError(f"Category {cat_code} not found in metadata")

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
        cred_code = payload["cred_code"]
        date = payload["date"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta.meta["creditors"].get(cred_code)
        if not creditor:
            raise ValueError(f"Creditor {cred_code} not found in metadata")

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
        cred_code = payload["cred_code"]
        date = payload["date"]
        amount = payload["amount"]

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta.meta["creditors"].get(cred_code)
        if not creditor:
            raise ValueError(f"Creditor {cred_code} not found in metadata")

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
        cred_code = payload["cred_code"]
        date = payload["date"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta.meta["creditors"].get(cred_code)
        if not creditor:
            raise ValueError(f"Creditor {cred_code} not found in metadata")

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
        cred_code = payload["cred_code"]
        date = payload["date"]
        amount = payload["amount"]

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta.meta["creditors"].get(cred_code)
        if not creditor:
            raise ValueError(f"Creditor {cred_code} not found in metadata")

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
        cred_code = payload["cred_code"]
        date = payload["date"]
        amount = payload["amount"]
        comment = payload.get("comment", "")

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta.meta["creditors"].get(cred_code)
        if not creditor:
            raise ValueError(f"Creditor {cred_code} not found in metadata")

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
        cred_code = payload["cred_code"]
        date = payload["date"]
        amount = payload["amount"]

        col = self.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")
        creditor = self.meta.meta["creditors"].get(cred_code)
        if not creditor:
            raise ValueError(f"Creditor {cred_code} not found in metadata")

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

    async def month_totals(
            self,
            ym: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_balances: bool = False,
    ) -> Dict[str, Any]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.month_totals(ym, level=level, zero_suppress=zero_suppress,
                                               include_balances=include_balances)

    async def months_overview(
            self,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_balances: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()
        return await self.numeric.months_overview(level=level, zero_suppress=zero_suppress,
                                                  include_balances=include_balances)
