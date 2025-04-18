# gateway/app/main.py

import os
from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator
import redis.asyncio as aioredis

load_dotenv()

app = FastAPI(title='Finance‑Gateway', version='0.1.0')

# Регистрируем Prometheus‑метрики сразу
Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")

# Настройка Redis
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis: aioredis.Redis | None = None


@app.on_event('startup')
async def on_start():
    global redis
    # Настраиваем логирование в stdout в формате JSON
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO", serialize=True)
    logger.info("⏱ Gateway starting…")

    # Подключаемся к Redis
    redis = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    logger.info(f"🔗 Connected to Redis at {REDIS_URL}")

    # Сохраняем клиент в state для роутов
    app.state.redis = redis


@app.on_event('shutdown')
async def on_shutdown():
    if redis:
        await redis.close()
        logger.info("🔌 Redis connection closed")


# Подключаем маршруты и проверку JWT
from .routes import operations  # noqa: E402
from .dependencies import verify_token  # noqa: E402

app.include_router(
    operations.router,
    prefix='/v1',
    dependencies=[Depends(verify_token)]
)
