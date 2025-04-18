# tests/test_sheets_data.py

import os
import json
import pytest
import re
from datetime import datetime

import gateway.app.services.sheets as sheets_module
from gateway.app.services.sheets import SheetsService, CACHE_KEY, DEFAULT_TTL

# Фейковые объекты для тестирования
class FakeWs:
    def __init__(self, rows):
        self.rows = rows
        self.get_calls = 0
    def get_all_values(self, include_tailing_empty=False):
        self.get_calls += 1
        return self.rows

class FakeSh:
    def __init__(self, ws):
        self._ws = ws
    def worksheet_by_title(self, title):
        return self._ws

class FakeClient:
    def __init__(self, ws):
        self.ws = ws
    def open_by_url(self, url):
        return FakeSh(self.ws)

class FakeRedis:
    def __init__(self):
        self.store = {}
        self.deleted_keys = []
    async def get(self, key):
        return self.store.get(key)
    async def set(self, key, value, ex=None):
        self.store[key] = value
    async def delete(self, key):
        self.deleted_keys.append(key)

@pytest.fixture(autouse=True)
def patch_pygsheets_authorize(monkeypatch):
    """
    Подменяем pygsheets.authorize на фабрику FakeClient со специфическим FakeWs.
    """
    monkeypatch.setenv('SPREADSHEET_URL', 'https://dummy')
    monkeypatch.setenv('SHEETS_SERVICE_FILE', '/no/need')
    # monkeypatch для sheets_module.pygsheets.authorize внутри SheetsService
    def fake_authorize(service_file):
        # rows держим в nonlocal
        return fake_client
    monkeypatch.setattr(sheets_module.pygsheets, 'authorize', fake_authorize)
    yield

@pytest.mark.asyncio
async def test_get_all_data_and_cache(monkeypatch):
    # Пример таблицы: пять строк, где 5-я (index=4) - даты
    rows = [
        ['','ignore','ignore'],
        ['','Р0','Раздел0'],
        ['','',''],
        ['','',''],
        ['','', '18.04.2025', '19.04.2025']
    ]
    fake_ws = FakeWs(rows)
    fake_client = FakeClient(fake_ws)
    fake_redis = FakeRedis()

    service = SheetsService(fake_redis)

    # Первый вызов: кеш пуст, читаем из ws
    data = await service.get_all_data()
    assert fake_ws.get_calls == 1
    # Проверяем структуру data
    assert data['column_b_values'] == ['', 'Р0', '', '', '']
    assert data['dates_row'] == ['','', '18.04.2025', '19.04.2025']
    # Должен быть записан в кеш
    cached = fake_redis.store.get(CACHE_KEY)
    assert cached is not None
    # Число TTL соответствует DEFAULT_TTL
    # (set не хранит ex в FakeRedis, но ключи совпадают)

    # Второй вызов: возвращаем из кеша, ws не дергается
    data2 = await service.get_all_data()
    assert fake_ws.get_calls == 1
    assert data2 == data

@pytest.mark.asyncio
async def test_data_extraction_methods():
    # Подготовим data вручную
    data = {
        'column_b_values': ['','Р0','1.2','1.3','Итого'],
        'column_c_values': ['','Раздел0','Категория12','Категория13','Итого'],
        'dates_row': ['','18.04.2025','19.04.2025'],
        'all_rows': []
    }
    service = SheetsService(redis=None)  # Redis не нужен для этих методов
    # Проверяем главы
    chapters = service.get_chapters(data)
    assert 'Р0' in chapters and chapters['Р0']=='Раздел0'
    # Проверяем категории раздела Р0
    cats = service.get_categories(data, 'Р0')
    assert '1.2' in cats and cats['1.2']=='Категория12'
    # Подкатегории: на примере добавим 'Р0','1.2','1.2.1'
    data2 = data.copy()
    data2['column_b_values'] = ['','Р0','1.2','1.2.1','Итого']
    data2['column_c_values'] = ['','Раздел0','Кат12','Подкат12','Итого']
    subs = service.get_subcategories(data2,'Р0','1.2')
    assert '1.2.1' in subs and subs['1.2.1']=='Подкат12'
    # Имена через методы
    assert service.get_chapter_name(data,'Р0')=='Раздел0'
    assert service.get_category_name(data,'Р0','1.2')=='Категория12'
    assert service.get_subcategory_name(data2,'Р0','1.2','1.2.1')=='Подкат12'
    # Поиск колонки по дате
    idx = service.find_column_by_date(data,'18.04.2025')
    assert idx==2
    # Не найден
    assert service.find_column_by_date(data,'01.01.2000') is None
