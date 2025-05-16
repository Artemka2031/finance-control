import asyncio
import json
import logging
from typing import Dict, Optional
from bot.agent.agent import run_agent, section_cache, category_cache, subcategory_cache, creditor_cache
from bot.api_client import ApiClient, ExpenseIn
from bot.config import BACKEND_URL
from bot.utils.logging import configure_logger

# Настройка логирования с фильтром для исключения метаданных
class NoMetadataFilter(logging.Filter):
    def filter(self, record):
        return not ("[METADATA] Fetched metadata" in record.getMessage())

logger = configure_logger("[TEST_AGENT]", "blue")
handler = logging.StreamHandler()
handler.addFilter(NoMetadataFilter())
logger.handlers = [handler]  # Заменяем обработчики, чтобы применить фильтр

async def select_category(api_client: ApiClient, input_text: str, prev_result: Dict) -> Optional[str]:
    """Интерактивный выбор раздела, категории или подкатегории через консоль."""
    requests = prev_result.get("requests", [])
    if not requests:
        print("Ошибка: Нет запросов для обработки.")
        return None

    request = requests[0]
    missing = request.get("missing", [])
    if not missing:
        print("Все поля заполнены, уточнение не требуется.")
        return None

    clarification_field = missing[0]  # Берем первое поле, требующее уточнения
    print(f"\nДля расхода: {input_text}")
    print(f"Требуется уточнить: {clarification_field}")

    if clarification_field == "chapter_code":
        print("\nДоступные разделы:")
        sections = await api_client.get_sections()
        for sec in sections:
            print(f"{sec.code}: {sec.name}")
        choice = input("Выберите раздел (введите код, например, Р1): ").strip()
        if not any(sec.code == choice for sec in sections):
            print("Неверный раздел!")
            return None
        return f"CS:chapter_code={choice}"

    elif clarification_field == "category_code":
        chapter_code = request["entities"].get("chapter_code")
        if not chapter_code:
            print("Ошибка: Не указан раздел.")
            return None
        print(f"\nКатегории в разделе {chapter_code}:")
        categories = await api_client.get_categories(chapter_code)
        for cat in categories:
            print(f"{cat.code}: {cat.name}")
        choice = input("Выберите категорию (введите код, например, 1): ").strip()
        if not any(cat.code == choice for cat in categories):
            print("Неверная категория!")
            return None
        return f"CS:category_code={choice}"

    elif clarification_field == "subcategory_code":
        chapter_code = request["entities"].get("chapter_code")
        category_code = request["entities"].get("category_code")
        if not (chapter_code and category_code):
            print("Ошибка: Не указан раздел или категория.")
            return None
        print(f"\nПодкатегории в категории {category_code}:")
        subcategories = await api_client.get_subcategories(chapter_code, category_code)
        for sub in subcategories:
            print(f"{sub.code}: {sub.name}")
        choice = input("Выберите подкатегорию (введите код, например, 1.1): ").strip()
        if not any(sub.code == choice for sub in subcategories):
            print("Неверная подкатегория!")
            return None
        return f"CS:subcategory_code={choice}"

    print(f"Неизвестное поле для уточнения: {clarification_field}")
    return None

async def test_agent():
    """Тестирует агента с набором тестовых запросов, используя реальный ApiClient."""
    logger.info("Запуск тестов агента...")

    # Очищаем кэши перед тестами
    section_cache.clear()
    category_cache.clear()
    subcategory_cache.clear()
    creditor_cache.clear()

    async with ApiClient(base_url=BACKEND_URL) as api_client:
        # Тестовые случаи
        test_inputs = [
            "Купил Наташе кофе за 250",
            "Купил Наташе велосипед на день рождения за 15000",
        ]

        for i, input_text in enumerate(test_inputs, 1):
            logger.info(f"\nТест {i}: {input_text}")
            result = await run_agent(
                input_text=input_text,
                interactive=True
            )
            logger.info(f"Результат:\n{json.dumps(result, indent=2, ensure_ascii=False)}")

            # Проверяем, нужно ли уточнение
            requests = result.get("requests", [])
            if not requests:
                logger.error("Ошибка: Нет запросов в результате")
                continue

            request = requests[0]
            if request.get("missing"):
                selection = await select_category(api_client, input_text, result)
                if selection:
                    logger.info(f"\nВыбран: {selection}")
                    result = await run_agent(
                        input_text=input_text,
                        interactive=True,
                        selection=selection,
                        prev_state=result.get("state")
                    )
                    logger.info(f"Результат после выбора:\n{json.dumps(result, indent=2, ensure_ascii=False)}")

            # Если нет missing, отправляем расход в бэкенд
            if not request.get("missing"):
                expense = ExpenseIn(
                    date=request["entities"]["date"],
                    sec_code=request["entities"]["chapter_code"],
                    cat_code=request["entities"]["category_code"],
                    sub_code=request["entities"]["subcategory_code"],
                    amount=float(request["entities"]["amount"]),
                    comment=request["entities"]["comment"]
                )
                response = await api_client.add_expense(expense)
                if response.ok:
                    logger.info(f"Расход успешно добавлен, task_id: {response.task_id}")
                else:
                    logger.error(f"Ошибка при добавлении расхода: {response.detail}")

if __name__ == "__main__":
    asyncio.run(test_agent())