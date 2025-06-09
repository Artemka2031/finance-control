# bot/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Устанавливаем Poetry с версией, соответствующей локальной (2.1.3)
RUN pip install --no-cache-dir poetry==2.1.3

# Копируем файлы Poetry
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости через Poetry
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --no-root  # --no-root чтобы не устанавливать проект как пакет

# Копируем код приложения
COPY . .

EXPOSE 5000

CMD ["poetry", "run", "python", "main.py"]