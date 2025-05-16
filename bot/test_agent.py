import asyncio
import json
from typing import Dict
from bot.agent.agent import run_agent, section_cache, category_cache, subcategory_cache, creditor_cache
from bot.api_client import ApiClient, ExpenseIn
from bot.config import BACKEND_URL
from bot.utils.logging import configure_logger

logger = configure_logger("[TEST_AGENT]", "blue")

async def test_agent():
    """Тестирует агента с набором тестовых запросов, используя реальный ApiClient."""
    logger.info("Запуск тестов агента...")

    # Очищаем кэши перед тестами
    section_cache.clear()
    category_cache.clear()
    subcategory_cache.clear()
    creditor_cache.clear()

    async with ApiClient(base_url=BACKEND_URL) as api_client:
        # Получаем метаданные с бэкенда
        metadata = await api_client.get_metadata()
        if not metadata:
            logger.info("Ошибка: Не удалось получить метаданные с бэкенда")
            return

        # Тестовые случаи
        TEST_CASES = [
            {
                "input": "Купил Наташе кофе за 250",
                "expected": {
                    "intent": "add_expense",
                    "entities": {
                        "amount": "250.0",
                        "date": "16.05.2025",
                        "wallet": "project",
                        "chapter_code": "Р4",
                        "category_code": "1",
                        "subcategory_code": "1.2",
                        "creditor": None,
                        "coefficient": "1.0",
                        "comment": "кофе для Наташи"
                    },
                    "missing": []
                }
            },
            {
                "input": "Купил Наташе велосипед на день рождения за 15000",
                "expected": {
                    "intent": "add_expense",
                    "entities": {
                        "amount": "15000.0",
                        "date": "16.05.2025",
                        "wallet": "project",
                        "chapter_code": None,
                        "category_code": None,
                        "subcategory_code": None,
                        "creditor": None,
                        "coefficient": "1.0",
                        "comment": "велосипед для Наташи на день рождения"
                    },
                    "missing": ["chapter_code", "category_code", "subcategory_code"]
                }
            }
        ]

        for i, test_case in enumerate(TEST_CASES):
            logger.info(f"\nТест {i + 1}: {test_case['input']}")
            result = await run_agent(
                input_text=test_case["input"],
                interactive=True
            )
            logger.info(f"Результат:\n{json.dumps(result, indent=2, ensure_ascii=False)}")

            # Проверка результата
            requests = result.get("requests", [])
            if not requests:
                logger.info("Ошибка: Нет запросов в результате")
                continue

            request = requests[0]
            expected = test_case["expected"]
            is_valid = True

            # Проверка intent
            if request["intent"] != expected["intent"]:
                logger.info(f"Ошибка: intent ожидался {expected['intent']}, получен {request['intent']}")
                is_valid = False

            # Проверка entities
            for key, expected_value in expected["entities"].items():
                actual_value = request["entities"].get(key)
                if actual_value != str(expected_value) if expected_value is not None else actual_value:
                    logger.info(f"Ошибка в {key}: ожидалось {expected_value}, получено {actual_value}")
                    is_valid = False

            # Проверка missing
            if sorted(request["missing"]) != sorted(expected["missing"]):
                logger.info(f"Ошибка в missing: ожидалось {expected['missing']}, получено {request['missing']}")
                is_valid = False

            # Проверка клавиатуры для спорных случаев
            if expected["missing"]:
                messages = result.get("messages", [])
                if not messages or not messages[0].get("keyboard"):
                    logger.info("Ошибка: Ожидалась клавиатура для уточнения")
                    is_valid = False
                else:
                    keyboard = messages[0]["keyboard"]["inline_keyboard"]
                    # Получаем ожидаемые разделы с бэкенда
                    sections = await api_client.get_sections()
                    expected_buttons = [
                        {"text": sec.name, "callback_data": f"CS:chapter_code={sec.code}"}
                        for sec in sections
                        if sec.code in ["Р1", "Р3"]  # Ограничиваем для теста
                    ]
                    actual_buttons = [btn for row in keyboard for btn in row if btn["callback_data"] != "cancel"]
                    actual_button_dict = {btn["callback_data"]: btn["text"] for btn in actual_buttons}
                    for expected_btn in expected_buttons:
                        if expected_btn["callback_data"] not in actual_button_dict:
                            logger.info(f"Ошибка: Ожидалась кнопка {expected_btn}, не найдена в {actual_buttons}")
                            is_valid = False
                        elif actual_button_dict[expected_btn["callback_data"]] != expected_btn["text"]:
                            logger.info(
                                f"Ошибка: Текст кнопки для {expected_btn['callback_data']} ожидался {expected_btn['text']}, получен {actual_button_dict[expected_btn['callback_data']]}")
                            is_valid = False

            # Если тест успешен и нет missing, отправляем расход в бэкенд
            if is_valid and not request["missing"]:
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
                    logger.info(f"Ошибка при добавлении расхода: {response.detail}")
                    is_valid = False

            logger.info("Тест пройден" if is_valid else "Тест не пройден")

            # Имитация выбора пользователя для спорных случаев
            if expected["missing"]:
                selection = "CS:chapter_code=Р1"
                logger.info(f"\nИмитация выбора: {selection}")
                result = await run_agent(
                    input_text=test_case["input"],
                    interactive=True,
                    selection=selection,
                    prev_state=result.get("state")
                )
                logger.info(f"Результат после выбора:\n{json.dumps(result, indent=2, ensure_ascii=False)}")

                # Проверка результата после выбора
                requests = result.get("requests", [])
                if not requests:
                    logger.info("Ошибка: Нет запросов после выбора")
                    continue
                request = requests[0]
                if request["entities"].get("chapter_code") != "Р1":
                    logger.info(
                        f"Ошибка: После выбора ожидался chapter_code='Р1', получен {request['entities'].get('chapter_code')}")
                    is_valid = False
                if "chapter_code" in request["missing"]:
                    logger.info("Ошибка: chapter_code всё ещё в missing после выбора")
                    is_valid = False
                logger.info("Тест выбора пройден" if is_valid else "Тест выбора не пройден")

if __name__ == "__main__":
    asyncio.run(test_agent())