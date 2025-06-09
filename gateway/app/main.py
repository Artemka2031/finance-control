import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from .services import GoogleSheetsService
from .services.operations.task_storage import init_db
from .services.core.config import REDIS_URL, FASTAPI_PORT, log

# Добавляем корень проекта в sys.path (если нужен импорт по корню)
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR.parent.parent))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт / Shutdown."""
    redis = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    log.info(f"🔗 Connected to Redis at {REDIS_URL}")
    app.state.redis = redis

    init_db()  # таблица точно создаётся
    service = GoogleSheetsService()
    await service.initialize()
    log.info("GoogleSheetsService initialized")

    yield

    if hasattr(service, "_worker_task") and service._worker_task:
        service._worker_task.cancel()
        try:
            await service._worker_task
        except asyncio.CancelledError:
            log.info("GoogleSheetsService worker task cancelled")

    await redis.close()
    log.info("🔌 Redis connection closed")
    log.info("Gateway shutdown complete")


app = FastAPI(
    title="Finance‑Gateway",
    version="0.1.0",
    lifespan=lifespan,  # <‑‑ lifespan передаём прямо в конструктор
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роуты операций
from .routes import operations  # noqa: E402

app.include_router(operations.router)


# Логирование времени отклика
@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    log.info(
        f"{request.method} {request.url.path} finished in {duration:.2f} ms "
        f"({response.status_code})"
    )
    return response


# Prometheus
Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    log.info(f"Starting gateway on port {FASTAPI_PORT}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=FASTAPI_PORT, reload=False)
