# gateway/app/services/sheets.py
"""
Работа с Google Sheets + кеш Redis.
Внизу файла есть CLI‑блок для быстрого просмотра:
- приходов,
- категорий/подкатегорий приходов,
- разделов, категорий, подкатегорий,
- кредиторов.

Запуск из корня проекта:
    python gateway/app/services/sheets.py
"""

import os
import json
import logging
import re
from typing import Any, Dict, List, Optional

import pygsheets
from dotenv import load_dotenv
from redis.asyncio import Redis

load_dotenv()
logger = logging.getLogger(__name__)

CACHE_KEY = "sheets:all_data"
DEFAULT_TTL = int(os.getenv("SHEETS_CACHE_TTL", 300))      # сек


# ──────────────────────────────────────────────────────────────
#                        CORE‑класс
# ──────────────────────────────────────────────────────────────
class SheetsService:
    def __init__(self, redis: Redis) -> None:
        creds = os.getenv("SHEETS_SERVICE_FILE", "./creds.json")
        url   = os.getenv("SPREADSHEET_URL")
        if not url:
            raise RuntimeError("SPREADSHEET_URL не задан в .env")

        self.redis = redis
        self.gc    = pygsheets.authorize(service_file=creds)
        self.sh    = self.gc.open_by_url(url)
        self.ws    = self.sh.worksheet_by_title("Общая таблица")
        logger.info("🔗 SheetsService initialised for %s", url)

    # ───── получение единого снапшота таблицы ─────
    async def get_all_data(self) -> Dict[str, Any]:
        try:
            cached = await self.redis.get(CACHE_KEY)
            if cached:
                logger.info("Using cached data")
                return json.loads(cached)
        except Exception as e:
            logger.warning("Redis get failed: %s", e)

        logger.info("Loading data from Google Sheets")
        rows: List[List[str]] = self.ws.get_all_values(include_tailing_empty=False)
        data: Dict[str, Any]  = {
            "column_b_values": [row[1] if len(row) > 1 else "" for row in rows],
            "column_c_values": [row[2] if len(row) > 2 else "" for row in rows],
            "dates_row"     : rows[4] if len(rows) > 4 else [],
            "all_rows"      : rows,
        }

        try:
            await self.redis.set(CACHE_KEY, json.dumps(data, ensure_ascii=False), ex=DEFAULT_TTL)
            logger.info("Data cached for %s s", DEFAULT_TTL)
        except Exception as e:
            logger.warning("Redis set failed: %s", e)

        return data

    # ───── справочные методы ─────
    @staticmethod
    def get_coming(data: Dict[str, Any]) -> Dict[str, str]:
        codes, names = data["column_b_values"], data["column_c_values"]
        return {code: names[i] for i, code in enumerate(codes) if code == "П"}

    @staticmethod
    def get_chapters(data: Dict[str, Any]) -> Dict[str, str]:
        codes, names = data["column_b_values"], data["column_c_values"]
        patt = re.compile(r"^Р\d+$")
        return {
            code: (names[i].split(":", 1)[-1].strip() if ":" in names[i] else names[i])
            for i, code in enumerate(codes) if patt.match(code)
        }

    @staticmethod
    def get_categories(data: Dict[str, Any], chapter_code: str) -> Dict[str, str]:
        codes, names = data["column_b_values"], data["column_c_values"]
        start = codes.index(chapter_code) + 1
        cats  = {}
        for i in range(start, len(codes)):
            if codes[i].startswith("Итого"):
                break
            if "." not in codes[i]:
                cats[codes[i]] = names[i]
        return cats

    @staticmethod
    def get_subcategories(data: Dict[str, Any], chapter_code: str, category_code: str) -> Dict[str, str]:
        codes, names = data["column_b_values"], data["column_c_values"]
        start = codes.index(category_code) + 1
        subs  = {}
        for i in range(start, len(codes)):
            code = codes[i]
            if code.startswith("Итого") or (re.match(r"^Р\d+$", code) and code != chapter_code):
                break
            if code.startswith(f"{category_code}."):
                subs[code] = names[i]
        return subs

    @staticmethod
    def find_column_by_date(data: Dict[str, Any], date: str) -> Optional[int]:
        for idx, d in enumerate(data.get("dates_row", [])):
            if d == date:
                return idx + 1
        return None


# ──────────────────────────────────────────────────────────────
#                       CLI‑проверка
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import redis.asyncio as aioredis


    def col_to_letter(num: int) -> str:
        """1‑A, 27‑AA …"""
        letters = ""
        while num > 0:
            num, rem = divmod(num - 1, 26)
            letters  = chr(65 + rem) + letters
        return letters

    async def main() -> None:
        redis_url   = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        service      = SheetsService(redis_client)

        data      = await service.get_all_data()
        column_b  = data["column_b_values"]

        # ─── Приходы ───
        print("Приходы:")
        for code, name in service.get_coming(data).items():
            row = column_b.index(code) + 1
            print(f"  {code} (row {row}): {name}")

        # Категории + подкатегории прихода
        print("\nКатегории приходов:")
        cats_in = service.get_categories(data, "П")
        for ccode, cname in cats_in.items():
            c_row = column_b.index(ccode) + 1
            print(f"  {ccode} (row {c_row}): {cname}")

            subs_in = service.get_subcategories(data, "П", ccode)
            for scode, sname in subs_in.items():
                s_row = column_b.index(scode) + 1
                print(f"    {scode} (row {s_row}): {sname}")

        # ─── Разделы, категории, подкатегории ───
        print("\nРазделы, категории, подкатегории:")
        for ch_code, ch_name in service.get_chapters(data).items():
            ch_row = column_b.index(ch_code) + 1
            print(f"{ch_code} (row {ch_row}): {ch_name}")

            cats = service.get_categories(data, ch_code)
            for cat_code, cat_name in cats.items():
                cat_row = column_b.index(cat_code) + 1
                print(f"  {cat_code} (row {cat_row}): {cat_name}")

                subs = service.get_subcategories(data, ch_code, cat_code)
                for sub_code, sub_name in subs.items():
                    sub_row = column_b.index(sub_code) + 1
                    print(f"    {sub_code} (row {sub_row}): {sub_name}")

        # ─── Кредиторы ───
        print("\nКредиторы:")
        try:
            start = column_b.index("К") + 1
            end   = column_b.index("Итоговая сумма экономии :", start)
            for i in range(start, end, 5):
                creditor = data["column_c_values"][i]
                row      = i + 1
                print(f"  {creditor} (row {row})")
        except ValueError:
            print("  Блок кредиторов не найден")

        # ─── Столбец по дате ───
        target_date = "18.04.2025"
        col_idx     = service.find_column_by_date(data, target_date)
        if col_idx:
            print(f"\nСтолбец для {target_date}: {col_idx} ({col_to_letter(col_idx)})")
        else:
            print(f"\nСтолбец {target_date} не найден")

        await redis_client.aclose()


    asyncio.run(main())
