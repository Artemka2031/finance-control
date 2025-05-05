from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Literal

from ..core import log, get_redis
from ..analytics.meta import SheetMeta
from ..analytics.numeric import SheetNumeric


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
        self.meta = None
        self.numeric = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        # Создаем экземпляр TaskManager
        from .task_manager import TaskManager
        self.task_manager = TaskManager(self)
        # Запускаем обработку задач в фоне сразу при создании экземпляра
        asyncio.create_task(self.task_manager.process_tasks())

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

    # Методы аналитики
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
