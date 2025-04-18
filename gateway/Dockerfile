# Исходная платформа
FROM python:3.11-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем корневой requirements.txt
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем сам код шлюза
COPY gateway/app ./app

# Открываем порт
EXPOSE 8000

# Команда запуска FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
