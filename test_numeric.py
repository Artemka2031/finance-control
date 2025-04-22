import asyncio
import json
import os
from gateway.app.services.sheets_numeric import SheetNumeric

async def run_tests():
    os.makedirs("tests", exist_ok=True)
    sn = SheetNumeric()

    # Запрос 1: Данные за 25.11.2024 без нулевых значений
    try:
        result1 = await sn.day_breakdown("25.11.2024", zero_suppress=True)
        with open("tests/request1_25_11_2024_no_zeros.json", "w", encoding="utf-8") as f:
            json.dump(result1, f, ensure_ascii=False, indent=4)
        print("Request 1 saved to tests/request1_25_11_2024_no_zeros.json")
    except ValueError as e:
        print(f"Error in request 1: {e}")

    # Запрос 2: Данные о расходах за период 25.11.2024 - 01.12.2024
    try:
        result2 = await sn.period_expense_summary("25.11.2024", "01.12.2024", level="subcategory", zero_suppress=True)
        with open("tests/request2_expenses_25_11_to_01_12.json", "w", encoding="utf-8") as f:
            json.dump(result2, f, ensure_ascii=False, indent=4)
        print("Request 2 saved to tests/request2_expenses_25_11_to_01_12.json")
    except ValueError as e:
        print(f"Error in request 2: {e}")

    # Запрос 3: Данные за 10.12.2024 с информацией о месяце
    try:
        result3 = await sn.day_breakdown("10.12.2024", include_month_summary=True)
        with open("tests/request3_10_12_2024_with_month.json", "w", encoding="utf-8") as f:
            json.dump(result3, f, ensure_ascii=False, indent=4)
        print("Request 3 saved to tests/request3_10_12_2024_with_month.json")
    except ValueError as e:
        print(f"Error in request 3: {e}")

    # Запрос 4: Данные о месяце (декабрь 2024)
    try:
        result4 = await sn.get_month_summary("2024-12")
        with open("tests/request4_month_summary_2024_12.json", "w", encoding="utf-8") as f:
            json.dump(result4, f, ensure_ascii=False, indent=4)
        print("Request 4 saved to tests/request4_month_summary_2024_12.json")
    except ValueError as e:
        print(f"Error in request 4: {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())