import os
from typing import List, Dict, Any, Literal, Optional, Tuple

import aiohttp
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Загружаем переменные окружения из .env
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")

# Проверка BACKEND_URL
if not BACKEND_URL:
    raise ValueError("BACKEND_URL is not set in .env file. Please add it to P:\\Python\\finance-control\\.env")

# Модели данных, соответствующие эндпоинтам
class CodeName(BaseModel):
    code: str
    name: str

class AckOut(BaseModel):
    ok: bool = True
    task_id: Optional[str] = None
    detail: Optional[List[dict]] = None

class ExpenseIn(BaseModel):
    date: str = Field(..., examples=["01.05.25"])
    sec_code: str = Field(..., alias="sec_code")
    cat_code: str = Field(..., alias="cat_code")
    sub_code: str = Field(..., alias="sub_code")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class IncomeIn(BaseModel):
    date: str = Field(..., examples=["01.05.25"])
    cat_code: str = Field(..., alias="cat_code")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class CreditorIn(BaseModel):
    cred_code: str = Field(..., alias="cred_code")
    date: str = Field(..., examples=["01.05.25"])
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class ApiClient:
    def __init__(self, base_url: str = BACKEND_URL):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self):
        """Ленивая инициализация aiohttp.ClientSession."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def __aenter__(self):
        """Вход в асинхронный контекстный менеджер."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Выход из асинхронного контекстного менеджера."""
        await self.close()

    async def close(self):
        """Закрытие сессии aiohttp."""
        if self.session and not self.session.closed:
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
                builder.add(
                    InlineKeyboardButton(
                        text=text,
                        callback_data=callback.pack() if hasattr(callback, "pack") else callback
                    )
                )
        if back_button and back_callback:
            builder.add(
                InlineKeyboardButton(
                    text="<< Назад",
                    callback_data=back_callback.pack() if hasattr(back_callback, "pack") else back_callback
                )
            )
        builder.adjust(adjust)
        return builder.as_markup()

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Внутренний метод для выполнения HTTP-запросов."""
        await self._ensure_session()
        try:
            async with self.session.request(method, f"{self.base_url}{endpoint}", **kwargs) as resp:
                data = await resp.json()
                if resp.status >= 400:
                    if "detail" in data and isinstance(data["detail"], str):
                        data["detail"] = [{"type": "error", "msg": data["detail"]}]
                    return {"detail": data.get("detail", [{"type": "http_error", "msg": f"HTTP {resp.status}"}])}
                return data
        except aiohttp.ClientError as e:
            return {"detail": [{"type": "request_error", "msg": str(e)}]}

    async def refresh_data(self) -> Dict[str, str]:
        """Обновление кэша и данных из Google Sheets."""
        return await self._make_request("POST", "/v1/service/refresh")

    async def get_metadata(self) -> Dict[str, Any]:
        """Получение полной структуры метаданных из Google Sheets."""
        return await self._make_request("GET", "/v1/service/meta")

    async def get_incomes(self) -> List[CodeName]:
        """Получение списка категорий доходов."""
        data = await self._make_request("GET", "/v1/keyboard/incomes")
        if "detail" in data:
            return []
        return [CodeName(**item) for item in data]

    async def get_sections(self) -> List[CodeName]:
        """Получение списка секций расходов."""
        data = await self._make_request("GET", "/v1/keyboard/sections")
        if "detail" in data:
            return []
        return [CodeName(**item) for item in data]

    async def get_categories(self, sec_code: str) -> List[CodeName]:
        """Получение списка категорий для заданной секции."""
        data = await self._make_request("GET", f"/v1/keyboard/categories/{sec_code}")
        if "detail" in data:
            return []
        return [CodeName(**item) for item in data]

    async def get_subcategories(self, sec_code: str, cat_code: str) -> List[CodeName]:
        """Получение списка подкатегорий для заданной секции и категории."""
        data = await self._make_request("GET", f"/v1/keyboard/subcategories/{sec_code}/{cat_code}")
        if "detail" in data:
            return []
        return [CodeName(**item) for item in data]

    async def get_creditors(self) -> List[CodeName]:
        """Получение списка кредиторов."""
        data = await self._make_request("GET", "/v1/keyboard/creditors")
        if "detail" in data:
            return []
        return [CodeName(**item) for item in data]

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
        return await self._make_request("GET", f"/v1/analytics/day/{date}", params=params)

    async def get_month_summary(self, ym: str, include_comments: bool = True) -> Dict[str, Any]:
        """Получение сводки за месяц."""
        params = {"include_comments": include_comments}
        return await self._make_request("GET", f"/v1/operations/month/{ym}", params=params)

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
        return await self._make_request("GET", f"/v1/analytics/period/{start_date}/{end_date}", params=params)

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
        return await self._make_request("GET", f"/v1/analytics/month_totals/{ym}", params=params)

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
        return await self._make_request("GET", "/v1/analytics/months_overview", params=params)

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Получение статуса задачи из очереди."""
        return await self._make_request("GET", f"/v1/operations/task/{task_id}")

    async def add_expense(self, expense: ExpenseIn) -> AckOut:
        """Добавление расхода в очередь задач."""
        data = await self._make_request("POST", "/v1/operations/expense/",
                                        json=expense.model_dump(by_alias=True, exclude_none=True))
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def remove_expense(self, task_id: str) -> AckOut:
        """Удаление расхода по task_id."""
        data = await self._make_request("POST", f"/v1/operations/expense/remove?task_id={task_id}")
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def add_income(self, income: IncomeIn) -> AckOut:
        """Добавление дохода в очередь задач."""
        data = await self._make_request("POST", "/v1/operations/income/",
                                        json=income.model_dump(by_alias=True, exclude_none=True))
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def remove_income(self, task_id: str) -> AckOut:
        """Удаление дохода по task_id."""
        data = await self._make_request("POST", f"/v1/operations/income/remove?task_id={task_id}")
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def record_borrowing(self, borrowing: CreditorIn) -> AckOut:
        """Запись займа в очередь задач."""
        data = await self._make_request("POST", "/v1/operations/creditor/borrow",
                                        json=borrowing.model_dump(by_alias=True, exclude_none=True))
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def remove_borrowing(self, task_id: str) -> AckOut:
        """Удаление займа по task_id."""
        data = await self._make_request("POST", f"/v1/operations/creditor/borrow/remove?task_id={task_id}")
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def record_repayment(self, repayment: CreditorIn) -> AckOut:
        """Запись погашения долга в очередь задач."""
        data = await self._make_request("POST", "/v1/operations/creditor/repay",
                                        json=repayment.model_dump(by_alias=True, exclude_none=True))
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def remove_repayment(self, task_id: str) -> AckOut:
        """Удаление погашения долга по task_id."""
        data = await self._make_request("POST", f"/v1/operations/creditor/repay/remove?task_id={task_id}")
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def record_saving(self, saving: CreditorIn) -> AckOut:
        """Запись сбережения в очередь задач."""
        data = await self._make_request("POST", "/v1/operations/creditor/save",
                                        json=saving.model_dump(by_alias=True, exclude_none=True))
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)

    async def remove_saving(self, task_id: str) -> AckOut:
        """Удаление сбережения по task_id."""
        data = await self._make_request("POST", f"/v1/operations/creditor/save/remove?task_id={task_id}")
        if "detail" in data:
            return AckOut(ok=False, detail=data["detail"])
        return AckOut(**data)