# gateway/app/routes/operations.py
from typing import Dict, Literal, Any, List

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field

from ..services.core import log
from ..services.operations import GoogleSheetsService

# Основной роутер
router = APIRouter()

# Подроутеры для групп
service_router = APIRouter(prefix="/service", tags=["Service"])
keyboard_router = APIRouter(prefix="/keyboard", tags=["Keyboard"])
analytics_router = APIRouter(prefix="/analytics", tags=["Analytics"])
operations_router = APIRouter(prefix="/operations", tags=["Operations"])

# Зависимость для получения сервиса
async def get_sheets_service() -> GoogleSheetsService:
    return await GoogleSheetsService.get_instance()

# Модели для входных данных
class ExpenseIn(BaseModel):
    date: str = Field(..., example="01.05.25")
    chapter: str = Field(..., alias="sec_code")
    category: str = Field(..., alias="cat_code")
    subcategory: str = Field(..., alias="sub_code")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class IncomeIn(BaseModel):
    date: str = Field(..., example="01.05.25")
    category: str = Field(..., alias="cat_code")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class CreditorIn(BaseModel):
    creditor_name: str = Field(..., alias="cred_code")
    date: str = Field(..., example="01.05.25")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

# Модели для выходных данных
class TaskOut(BaseModel):
    task_id: str

class AckOut(BaseModel):
    ok: bool = True
    task_id: str

class CodeName(BaseModel):
    code: str
    name: str

# --- Служебные ручки ---
@service_router.post("/refresh", summary="Refresh cache and data")
async def refresh_data(service: GoogleSheetsService = Depends(get_sheets_service)) -> Dict[str, str]:
    """Force refresh of cache and metadata from Google Sheets."""
    try:
        await service.refresh_cache()
        return {"status": "success", "message": "Cache and data refreshed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh cache: {str(e)}")

@service_router.get("/meta", response_model=Dict, summary="Get full metadata")
async def get_metadata(service: GoogleSheetsService = Depends(get_sheets_service)):
    """Retrieve the complete metadata structure from Google Sheets."""
    log.info("Fetching metadata from GoogleSheetsService")
    try:
        meta = service.meta.meta
        log.info(f"Metadata fetched: date_cols={list(meta['date_cols'].keys())}")
        return meta
    except Exception as e:
        log.error(f"Failed to fetch metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch metadata: {str(e)}")

# --- Ручки для клавиатур ---
@keyboard_router.get(
    "/incomes",
    response_model=List[CodeName],
    summary="Get list of income categories"
)
async def get_incomes(service: GoogleSheetsService = Depends(get_sheets_service)):
    """Retrieve a list of income categories with their codes and names."""
    try:
        incomes = [
            {"code": cat_code, "name": cat["name"]}
            for cat_code, cat in service.meta.meta["income"].get("cats", {}).items()
        ]
        log.info(f"Fetched {len(incomes)} income categories")
        return incomes
    except Exception as e:
        log.error(f"Failed to fetch incomes: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch incomes: {str(e)}")

@keyboard_router.get(
    "/sections",
    response_model=List[CodeName],
    summary="Get list of expense sections"
)
async def get_sections(service: GoogleSheetsService = Depends(get_sheets_service)):
    """Retrieve a list of expense sections with their codes and names."""
    try:
        sections = [
            {"code": sec_code, "name": sec["name"]}
            for sec_code, sec in service.meta.meta["expenses"].items()
        ]
        log.info(f"Fetched {len(sections)} expense sections")
        return sections
    except Exception as e:
        log.error(f"Failed to fetch sections: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch sections: {str(e)}")

@keyboard_router.get(
    "/categories/{sec_code}",
    response_model=List[CodeName],
    summary="Get list of categories for a section"
)
async def get_categories(
    sec_code: str,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Retrieve a list of categories for a given expense section."""
    try:
        section = service.meta.meta["expenses"].get(sec_code)
        if not section:
            raise HTTPException(status_code=404, detail=f"Section {sec_code} not found")
        categories = [
            {"code": cat_code, "name": cat["name"]}
            for cat_code, cat in section.get("cats", {}).items()
        ]
        log.info(f"Fetched {len(categories)} categories for section {sec_code}")
        return categories
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to fetch categories for section {sec_code}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch categories: {str(e)}")

@keyboard_router.get(
    "/subcategories/{sec_code}/{cat_code}",
    response_model=List[CodeName],
    summary="Get list of subcategories for a category"
)
async def get_subcategories(
    sec_code: str,
    cat_code: str,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Retrieve a list of subcategories for a given section and category."""
    try:
        section = service.meta.meta["expenses"].get(sec_code)
        if not section:
            raise HTTPException(status_code=404, detail=f"Section {sec_code} not found")
        category = section.get("cats", {}).get(cat_code)
        if not category:
            raise HTTPException(status_code=404, detail=f"Category {cat_code} not found")
        subcategories = [
            {"code": sub_code, "name": sub["name"]}
            for sub_code, sub in category.get("subs", {}).items()
        ]
        log.info(f"Fetched {len(subcategories)} subcategories for {sec_code}/{cat_code}")
        return subcategories
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to fetch subcategories for {sec_code}/{cat_code}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch subcategories: {str(e)}")

@keyboard_router.get(
    "/creditors",
    response_model=List[CodeName],
    summary="Get list of creditors"
)
async def get_creditors(service: GoogleSheetsService = Depends(get_sheets_service)):
    """Retrieve a list of creditors with their codes and names."""
    try:
        creditors = [
            {"code": cred_code, "name": service.meta.col_c[cred["base"] - 1].strip()}
            for cred_code, cred in service.meta.meta["creditors"].items()
        ]
        log.info(f"Fetched {len(creditors)} creditors")
        return creditors
    except Exception as e:
        log.error(f"Failed to fetch creditors: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch creditors: {str(e)}")

# --- Ручки аналитики ---
@analytics_router.get(
    "/day/{date}",
    summary="Get daily breakdown"
)
async def day_breakdown(
    date: str,
    level: Literal["section", "category", "subcategory"] = "subcategory",
    zero_suppress: bool = False,
    include_month_summary: bool = False,
    include_comments: bool = True,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    """Retrieve a detailed breakdown of financial data for a specific day."""
    try:
        return await service.day_breakdown(date, level, zero_suppress, include_month_summary, include_comments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@analytics_router.get(
    "/month/{ym}",
    summary="Get monthly summary"
)
async def get_month_summary(
    ym: str,
    include_comments: bool = True,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    """Retrieve a summary of financial data for a specific month."""
    try:
        return await service.get_month_summary(ym, include_comments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@analytics_router.get(
    "/period/{start_date}/{end_date}",
    summary="Get period expense summary"
)
async def period_expense_summary(
    start_date: str,
    end_date: str,
    level: Literal["section", "category", "subcategory"] = "subcategory",
    zero_suppress: bool = False,
    include_comments: bool = True,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    """Retrieve a summary of expenses for a specific period."""
    try:
        return await service.period_expense_summary(start_date, end_date, level, zero_suppress, include_comments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@analytics_router.get(
    "/month_totals/{ym}",
    summary="Get monthly totals",
    response_model=Dict[str, Any]
)
async def month_totals(
    ym: str,
    level: Literal["section", "category", "subcategory"] = "subcategory",
    zero_suppress: bool = False,
    include_balances: bool = False,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    """Retrieve detailed income, expenses, creditors, and balances for a specific month."""
    try:
        return await service.month_totals(ym, level=level, zero_suppress=zero_suppress, include_balances=include_balances)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@analytics_router.get(
    "/months_overview",
    summary="Get financial overview for all months",
    response_model=Dict[str, Dict[str, Any]]
)
async def months_overview(
    level: Literal["section", "category", "subcategory"] = "subcategory",
    zero_suppress: bool = False,
    include_balances: bool = False,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Dict[str, Any]]:
    """Retrieve a detailed financial overview for all months, including income, expenses, creditors, and balances."""
    return await service.months_overview(level=level, zero_suppress=zero_suppress, include_balances=include_balances)

# --- Ручки операций ---
@operations_router.post("/expense", response_model=AckOut, summary="Add an expense")
async def add_expense(
    payload: ExpenseIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to add a new expense to the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("add_expense", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/expense/remove", response_model=AckOut, summary="Remove an expense")
async def remove_expense(
    payload: ExpenseIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to remove an expense from the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_expense", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/income", response_model=AckOut, summary="Add an income")
async def add_income(
    payload: IncomeIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to add a new income to the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("add_income", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/income/remove", response_model=AckOut, summary="Remove an income")
async def remove_income(
    payload: IncomeIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to remove an income from the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_income", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/creditor/borrow", response_model=AckOut, summary="Record a borrowing")
async def record_borrowing(
    payload: CreditorIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to record a borrowing in the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("record_borrowing", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/creditor/borrow/remove", response_model=AckOut, summary="Remove a borrowing")
async def remove_borrowing(
    payload: CreditorIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to remove a borrowing from the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_borrowing", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/creditor/repay", response_model=AckOut, summary="Record a repayment")
async def record_repayment(
    payload: CreditorIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to record a repayment in the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("record_repayment", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/creditor/repay/remove", response_model=AckOut, summary="Remove a repayment")
async def remove_repayment(
    payload: CreditorIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to remove a repayment from the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_repayment", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/creditor/save", response_model=AckOut, summary="Record a saving")
async def record_saving(
    payload: CreditorIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to record a saving in the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("record_saving", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.post("/creditor/save/remove", response_model=AckOut, summary="Remove a saving")
async def remove_saving(
    payload: CreditorIn,
    request: Request,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Queue a task to remove a saving from the Google Sheet."""
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_saving", payload.model_dump(by_alias=True), user_id)
    return AckOut(ok=True, task_id=task_id)

@operations_router.get("/task/{task_id}", response_model=Dict, summary="Get task status")
async def get_task_status(
    task_id: str,
    service: GoogleSheetsService = Depends(get_sheets_service)
):
    """Retrieve the status of a queued task."""
    try:
        return await service.get_task_status(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# Регистрация подроутеров
router.include_router(service_router, prefix="/v1")
router.include_router(keyboard_router, prefix="/v1")
router.include_router(analytics_router, prefix="/v1")
router.include_router(operations_router, prefix="/v1")
