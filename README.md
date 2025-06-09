# Руководство проекта Finance-Control

Добро пожаловать в проект `finance-control`! В этом репозитории содержится шлюзовое приложение на базе FastAPI (`gateway`) и бот (`bot`) для управления финансовыми задачами. Это руководство поможет вам настроить и запустить проект локально с помощью Poetry (без Docker) или через Docker Compose. Поскольку вы новичок в Poetry, мы пошагово разберём его установку и использование.

## Предварительные требования

- **Операционная система**: Windows (инструкции даны для Windows).
- **Python**: версия 3.11 или новее (проверьте `python --version`).
- **Git**: для клонирования репозитория (установить с [git-scm.com](https://git-scm.com/)).
- **Poetry** (для локального запуска без Docker).
- **Docker** и **Docker Compose** (для контейнерного запуска; установить с [docker.com](https://www.docker.com/)).

## Обзор проекта

- **`gateway/`** — FastAPI‑приложение, которое обрабатывает API‑запросы и взаимодействует с Google Sheets и Redis.  
- **`bot/`** — Telegram‑бот (в этом файле подробно не рассматривается, но включён в Docker Compose).  
- **Конфигурация** — используется файл `.env.dev` с переменными окружения, включая учетные данные Google.

## Установка и настройка

### 1. Установка Poetry

Poetry — это инструмент управления зависимостями и упаковки проектов Python. Для установки в Windows сделайте следующее:

1. **Скачайте и установите Poetry**  
   Откройте командную строку (CMD) или PowerShell и выполните:  
   ```powershell
   (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
   ```
   Команда установит Poetry глобально.

2. **Проверьте установку**  
   ```powershell
   poetry --version
   ```
   Должен появиться вывод вида `Poetry (version 1.8.x)`.

3. **Добавьте Poetry в PATH** (если не добавилось автоматически)  
   - Исполняемый файл Poetry обычно находится в `C:\Users\<ВашПользователь>\AppData\Roaming\Python\Poetry\Scripts`.  
   - Добавьте этот путь в системную переменную `Path`:  
     - Нажмите `Win + S`, введите «Переменные среды» и выберите «Изменить системные переменные среды».  
     - В окне «Свойства системы» нажмите «Переменные среды».  
     - Найдите `Path`, нажмите «Изменить…» и добавьте путь к каталогу `Scripts`.  
   - Закройте и заново откройте CMD/PowerShell и снова выполните `poetry --version`.

4. **Установите зависимости проекта**  
   ```powershell
   cd C:\path\to\finance-control
   poetry install
   ```
   Будет создано виртуальное окружение и установлены зависимости из `pyproject.toml` (Python ≥ 3.11).

### 2. Настройка переменных окружения

Проект использует файл `.env.dev` для конфигурации. Он содержит чувствительные данные, например учетные данные Google.

1. **Создайте `.env.dev`**  
   В каталоге `gateway/` создайте файл `.env.dev` (если его нет) и заполните:  
   ```dotenv
   ; gateway/.env
   SPREADSHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID
   REDIS_URL=redis://localhost:6379/0
   GS_MAX_ROWS=300
   WORKSHEET_NAME=Общая таблица
   FASTAPI_PORT=8000
   DATABASE_PATH=tasks.db
   GOOGLE_CREDENTIALS={"type":"service_account","project_id":"your_project_id","private_key_id":"your_private_key_id","private_key":"your_private_key","client_email":"your_client_email","client_id":"your_client_id","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/your_client_email"}
   PROJECT_ID=project1
   ```
   - **Получение учетных данных Google**  
     В Google Cloud Console создайте сервисный аккаунт и скачайте JSON‑ключ (`creds.json`). Скопируйте его содержимое в поле `GOOGLE_CREDENTIALS` как строку JSON.  
   - **SPREADSHEET_URL** — замените `YOUR_SPREADSHEET_ID` на ID вашей таблицы Google Sheets.

2. **Замечания по безопасности**  
   - Добавьте `.env.dev` в `.gitignore`, чтобы не коммитить секреты.  
   - Никогда не публикуйте `.env.dev`.

### 3. Генерация lock‑файла

Для фиксации версий зависимостей выполните в каталоге проекта:
```powershell
poetry lock
```
Файл `poetry.lock` зафиксирует конкретные версии пакетов — коммитите его в репозиторий.

## Запуск проекта

### Вариант 1: локально через Poetry (без Docker)

1. Перейдите в каталог `gateway`  
   ```powershell
   cd C:\path\to\finance-control\gateway
   ```

2. Активируйте виртуальное окружение  
   ```powershell
   poetry shell
   ```
   *или запускайте команды через* `poetry run`.

3. Запустите приложение  
   ```powershell
   poetry run python -m app.main
   ```
   Должны появиться логи вида:
   ```
   2025-06-09 12:50:00.123 | INFO     | app.services.core.config:<module>:46 - Configuration loaded: SPREADSHEET_URL=..., REDIS_URL=..., ...
   ⏱ Gateway starting…
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

4. Проверьте работу  
   Откройте `http://127.0.0.1:8000/docs` и вызовите `/health`.

5. Остановите приложение — `Ctrl + C`.

### Вариант 2: Docker Compose

1. **Установите Docker** — скачайте Docker Desktop.  
2. **Учётные данные Google как секрет**: положите `creds.json` в корень проекта под именем `google_credentials.json` (не коммитить).  
3. **Запустите**  
   ```powershell
   cd C:\path\to\finance-control
   docker-compose up --build
   ```
4. **Swagger UI** — `http://127.0.0.1:8000/docs`.  
5. **Остановите** — `Ctrl + C` или `docker-compose down`.  
6. **Файл `docker-compose.yml`** уже смонтирует секрет по пути `/run/secrets/google_credentials`.

## Решение проблем

- **Poetry**: убедитесь, что `poetry` в PATH и окружение активно.  
- **Конфигурация**: проверьте `.env.dev` и корректность JSON в `GOOGLE_CREDENTIALS`.  
- **Docker**: убедитесь, что Docker запущен, и проверьте логи `docker-compose logs`.

## Дополнительно

- **Рефакторинг**: проект использует централизованный `config.py` вместо валидации Pydantic.  
- **Зависимости**: управляются через `pyproject.toml`; для добавления пакетов используйте `poetry add <package>` и `poetry lock`.  

## Вклад

Открывайте issues и pull requests — предварительно выполните настройку по шагам выше.

Удачной разработки!
