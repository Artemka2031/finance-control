# gateway/app/main.py
import sys
import time
from pathlib import Path

from starlette.middleware.cors import CORSMiddleware

from .services import GoogleSheetsService

# Добавляем корневую папку проекта в sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # P:\Python\finance-control
sys.path.append(str(BASE_DIR))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator
import redis.asyncio as aioredis

from .routes import operations
from .services.core import REDIS_URL, log

app = FastAPI(title='Finance-Gateway', version='0.1.0')

# Настройка CORS (если требуется)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware для логирования времени выполнения запросов
@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = (time.time() - start_time) * 1000  # В миллисекундах
    log.info(
        f"Request: {request.method} {request.url.path} completed in {duration:.2f} ms, status: {response.status_code}"
    )
    return response

@app.on_event("startup")
async def startup_event():
    log.info("Application starting up")
    service = GoogleSheetsService()
    await service.initialize()
    log.info("GoogleSheetsService initialized on startup")

# Регистрируем Prometheus-метрики
Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")

# Настройка Redis
redis: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis
    # Startup
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        level="INFO",
        serialize=True
    )
    logger.info("⏱ Gateway starting…")

    redis = aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )
    logger.info(f"🔗 Connected to Redis at {REDIS_URL}")
    app.state.redis = redis

    yield

    # Shutdown
    if redis:
        await redis.close()
        logger.info("🔌 Redis connection closed")


app.lifespan = lifespan

app.include_router(operations.router, prefix='/v1')
