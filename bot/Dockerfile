FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем только код бота (в корень /app)
COPY bot/ .

# По желанию: положите creds.json сюда, если нужно

# Запуск
CMD ["python", "-u", "main.py"]
