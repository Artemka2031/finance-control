import os
from typing import List, Dict, Any, Literal, Optional, Tuple

import aiohttp
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from pydantic import BaseModel

# Загружаем переменные окружения из .env
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")


# Модели данных, соответствующие эндпоинтам
class CodeName(BaseModel):
    code: str
    name: str


class AckOut(BaseModel):
    ok: bool
    task_id: str


class ExpenseIn(BaseModel):
    date: str
    amount: float
    section_code: str
    category_code: str
    subcategory_code: str | None = None
    comment: str | None = None


class IncomeIn(BaseModel):
    date: str
    amount: float
    category_code: str
    comment: str | None = None


class CreditorIn(BaseModel):
    date: str
    amount: float
    creditor_code: str
    comment: str | None = None


class ApiClient:
    def __init__(self, base_url: str = BACKEND_URL):
        self.base_url = base_url
        self.session = aiohttp.ClientSession()

    async def close(self):
        """Закрытие сессии aiohttp."""
        await self.session.close()

    def build_inline_keyboard(
            self,
            items: List[Tuple[str, str, Optional[object]]],
            adjust: int = 1,
            back_button: bool = False,
            back_callback: Optional[object] = None
    ) -> InlineKeyboardMarkup:
        """Создает инлайн-клавиатуру."""
        builder = InlineKeyboardBuilder()
        for text, _, callback in items:
            if callback:
                builder.add(InlineKeyboardButton(text=text, callback_data=callback.pack()))
        if back_button and back_callback:
            builder.add(InlineKeyboardButton(text="<< Назад", callback_data=back_callback.pack()))
        builder.adjust(adjust)
        return builder.as_markup()

    # --- Служебные методы ---
    async def refresh_data(self) -> Dict[str, str]:
        """Обновление кэша и данных из Google Sheets."""
        async with self.session.post(f"{self.base_url}/v1/service/refresh") as resp:
            return await resp.json()

    async def get_metadata(self) -> Dict[str, Any]:
        """Получение полной структуры метаданных из Google Sheets."""
        async with self.session.get(f"{self.base_url}/v1/service/meta") as resp:
            return await resp.json()

    # --- Методы для клавиатур ---
    async def get_incomes(self) -> List[CodeName]:
        """Получение списка категорий доходов."""
        async with self.session.get(f"{self.base_url}/v1/keyboard/incomes") as resp:
            data = await resp.json()
            return [CodeName(**item) for item in data]

    async def get_sections(self) -> List[CodeName]:
        """Получение списка секций расходов."""
        async with self.session.get(f"{self.base_url}/v1/keyboard/sections") as resp:
            data = await resp.json()
            return [CodeName(**item) for item in data]

    async def get_categories(self, sec_code: str) -> List[CodeName]:
        """Получение списка категорий для заданной секции."""
        async with self.session.get(f"{self.base_url}/v1/keyboard/categories/{sec_code}") as resp:
            data = await resp.json()
            return [CodeName(**item) for item in data]

    async def get_subcategories(self, sec_code: str, cat_code: str) -> List[CodeName]:
        """Получение списка подкатегорий для заданной секции и категории."""
        async with self.session.get(f"{self.base_url}/v1/keyboard/subcategories/{sec_code}/{cat_code}") as resp:
            data = await resp.json()
            return [CodeName(**item) for item in data]

    async def get_creditors(self) -> List[CodeName]:
        """Получение списка кредиторов."""
        async with self.session.get(f"{self.base_url}/v1/keyboard/creditors") as resp:
            data = await resp.json()
            return [CodeName(**item) for item in data]

    # --- Методы аналитики ---
    async def day_breakdown(
            self,
            date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_month_summary: bool = False,
            include_comments: bool = True
    ) -> Dict[str, Any]:
        """Получение детализированного отчёта за день."""
        params = {
            "level": level,
            "zero_suppress": zero_suppress,
            "include_month_summary": include_month_summary,
            "include_comments": include_comments
        }
        async with self.session.get(f"{self.base_url}/v1/analytics/day/{date}", params=params) as resp:
            return await resp.json()

    async def get_month_summary(self, ym: str, include_comments: bool = True) -> Dict[str, Any]:
        """Получение сводки за месяц."""
        params = {"include_comments": include_comments}
        async with self.session.get(f"{self.base_url}/v1/analytics/month/{ym}", params=params) as resp:
            return await resp.json()

    async def period_expense_summary(
            self,
            start_date: str,
            end_date: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_comments: bool = True
    ) -> Dict[str, Any]:
        """Получение сводки расходов за период."""
        params = {
            "level": level,
            "zero_suppress": zero_suppress,
            "include_comments": include_comments
        }
        async with self.session.get(f"{self.base_url}/v1/analytics/period/{start_date}/{end_date}",
                                    params=params) as resp:
            return await resp.json()

    async def month_totals(
            self,
            ym: str,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_balances: bool = False
    ) -> Dict[str, Any]:
        """Получение итогов за месяц (доходы, расходы, кредиторы, балансы)."""
        params = {
            "level": level,
            "zero_suppress": zero_suppress,
            "include_balances": include_balances
        }
        async with self.session.get(f"{self.base_url}/v1/analytics/month_totals/{ym}", params=params) as resp:
            return await resp.json()

    async def months_overview(
            self,
            level: Literal["section", "category", "subcategory"] = "subcategory",
            zero_suppress: bool = False,
            include_balances: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """Получение финансового обзора по всем месяцам."""
        params = {
            "level": level,
            "zero_suppress": zero_suppress,
            "include_balances": include_balances
        }
        async with self.session.get(f"{self.base_url}/v1/analytics/months_overview", params=params) as resp:
            return await resp.json()

    # --- Методы операций ---
    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Получение статуса задачи из очереди."""
        async with self.session.get(f"{self.base_url}/v1/operations/task/{task_id}") as resp:
            return await resp.json()

    async def add_expense(self, expense: ExpenseIn) -> AckOut:
        """Добавление расхода в очередь задач."""
        async with self.session.post(f"{self.base_url}/v1/operations/expense/", json=expense.model_dump()) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def remove_expense(self, task_id: str) -> AckOut:
        """Удаление расхода по task_id."""
        async with self.session.post(f"{self.base_url}/v1/operations/expense/remove",
                                     json={"task_id": task_id}) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def add_income(self, income: IncomeIn) -> AckOut:
        """Добавление дохода в очередь задач."""
        async with self.session.post(f"{self.base_url}/v1/operations/income/", json=income.model_dump()) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def remove_income(self, task_id: str) -> AckOut:
        """Удаление дохода по task_id."""
        async with self.session.post(f"{self.base_url}/v1/operations/income/remove", json={"task_id": task_id}) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def record_borrowing(self, borrowing: CreditorIn) -> AckOut:
        """Запись займа в очередь задач."""
        async with self.session.post(f"{self.base_url}/v1/operations/creditor/borrow",
                                     json=borrowing.model_dump()) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def remove_borrowing(self, task_id: str) -> AckOut:
        """Удаление займа по task_id."""
        async with self.session.post(f"{self.base_url}/v1/operations/creditor/borrow/remove",
                                     json={"task_id": task_id}) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def record_repayment(self, repayment: CreditorIn) -> AckOut:
        """Запись погашения долга в очередь задач."""
        async with self.session.post(f"{self.base_url}/v1/operations/creditor/repay",
                                     json=repayment.model_dump()) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def remove_repayment(self, task_id: str) -> AckOut:
        """Удаление погашения долга по task_id."""
        async with self.session.post(f"{self.base_url}/v1/operations/creditor/repay/remove",
                                     json={"task_id": task_id}) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def record_saving(self, saving: CreditorIn) -> AckOut:
        """Запись сбережения в очередь задач."""
        async with self.session.post(f"{self.base_url}/v1/operations/creditor/save", json=saving.model_dump()) as resp:
            data = await resp.json()
            return AckOut(**data)

    async def remove_saving(self, task_id: str) -> AckOut:
        """Удаление сбережения по task_id."""
        async with self.session.post(f"{self.base_url}/v1/operations/creditor/save/remove",
                                     json={"task_id": task_id}) as resp:
            data = await resp.json()
            return AckOut(**data)
