import asyncio
import uuid
from typing import Any, Dict
import json
from datetime import datetime

from peewee import DoesNotExist

from .operations import Operations

from ..core.config import log
from .task_storage import Task


class TaskManager:
    def __init__(self, service):
        log.info("Initializing TaskManager")
        self.service = service
        self.task_queue = asyncio.PriorityQueue()
        self.sheet_lock = asyncio.Lock()
        self.cache_update_timer = None
        self.last_post_time = None
        self.cache_update_interval = 30  # seconds
        self._processing_task = None  # Tracks background task

    async def queue_task(self, task_type: str, payload: Dict[str, Any], user_id: str) -> str:
        async with self.service._init_lock:
            if not self.service._initialized:
                await self.service.initialize()
        # Generate a 16-character task_id from UUID4 to fit Telegram callback data limit (64 bytes)
        task_id = str(uuid.uuid4())[:13]
        priority = 1 if "remove" not in task_type else 2
        task = Task.create(
            task_id=task_id,
            priority=priority,
            task_type=task_type,
            payload=json.dumps(payload),
            user_id=user_id,
            status="queued",
            result=None
        )
        await self.task_queue.put((priority, task_id))
        log.info(f"Queued task {task_id} of type {task_type} for user {user_id}")

        # Start background task processing if not already running
        if self._processing_task is None or self._processing_task.done():
            self._processing_task = asyncio.create_task(self.process_tasks())

        # Update last POST time and schedule cache update
        self.last_post_time = datetime.now()
        self._schedule_cache_update()

        return task_id

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        async with self.service._init_lock:
            if not self.service._initialized:
                await self.service.initialize()
        try:
            task = Task.get(Task.task_id == task_id)
            return task.to_dict()
        except DoesNotExist:
            raise ValueError(f"Task {task_id} not found")

    async def process_tasks(self):
        from .operations import Operations
        operations = Operations(self.service)
        while True:
            try:
                priority, task_id = await self.task_queue.get()
                # Process each task in a separate coroutine
                asyncio.create_task(self._process_single_task(operations, task_id))
            except asyncio.CancelledError:
                log.info("Task processing cancelled")
                break
            except Exception as e:
                log.error(f"Error in process_tasks: {str(e)}")

    async def _process_single_task(self, operations: Operations, task_id: str):
        try:
            task = Task.get(Task.task_id == task_id)
        except DoesNotExist:
            log.error(f"Task {task_id} not found in database")
            self.task_queue.task_done()
            return

        log.info(f"Processing task {task.task_id} of type {task.task_type}")
        task.status = "processing"
        task.save()

        try:
            async with self.sheet_lock:
                payload = json.loads(task.payload)
                result = await operations.execute_task(task.task_type, payload)
                task.status = "completed"
                task.result = json.dumps(result)
                task.save()
                log.info(f"Task {task.task_id} completed successfully")
        finally:
            self.task_queue.task_done()

    def _schedule_cache_update(self):
        if self.cache_update_timer:
            self.cache_update_timer.cancel()
        self.cache_update_timer = asyncio.get_event_loop().call_later(
            self.cache_update_interval,
            lambda: asyncio.create_task(self._update_cache())
        )

    async def _update_cache(self):
        if self.last_post_time and (datetime.now() - self.last_post_time).seconds < self.cache_update_interval:
            self._schedule_cache_update()
            return
        log.info("Updating cache after delay")
        await self.service.refresh_cache()
