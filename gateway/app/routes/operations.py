# gateway/app/routes/operations.py
from typing import Dict, Literal, Any

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field

from ..services.core import log
from ..services.operations import GoogleSheetsService

router = APIRouter()


async def get_sheets_service() -> GoogleSheetsService:
    service = GoogleSheetsService()
    await service.initialize()
    return service

class ExpenseIn(BaseModel):
    date: str = Field(..., example="01.05.25")
    chapter: str
    category: str
    amount: float
    comment: str | None = None


class IncomeIn(BaseModel):
    date: str = Field(..., example="01.05.25")
    category: str
    amount: float
    comment: str | None = None


class CreditorIn(BaseModel):
    creditor_name: str
    date: str = Field(..., example="01.05.25")
    amount: float
    comment: str | None = None


class TaskOut(BaseModel):
    task_id: str

class AckOut(BaseModel):
    ok: bool = True
    task_id: str


@router.post("/expense", response_model=AckOut)
async def add_expense(
        payload: ExpenseIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("add_expense", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/expense/remove", response_model=AckOut)
async def remove_expense(
        payload: ExpenseIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_expense", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/income", response_model=AckOut)
async def add_income(
        payload: IncomeIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("add_income", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/income/remove", response_model=AckOut)
async def remove_income(
        payload: IncomeIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_income", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/creditor/borrow", response_model=AckOut)
async def record_borrowing(
        payload: CreditorIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("record_borrowing", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/creditor/borrow/remove", response_model=AckOut)
async def remove_borrowing(
        payload: CreditorIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_borrowing", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/creditor/repay", response_model=AckOut)
async def record_repayment(
        payload: CreditorIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("record_repayment", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/creditor/repay/remove", response_model=AckOut)
async def remove_repayment(
        payload: CreditorIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_repayment", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/creditor/save", response_model=AckOut)
async def record_saving(
        payload: CreditorIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("record_saving", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.post("/creditor/save/remove", response_model=AckOut)
async def remove_saving(
        payload: CreditorIn,
        request: Request,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    user_id = request.headers.get("X-User-ID", "unknown")
    task_id = await service.queue_task("remove_saving", payload.model_dump(), user_id)
    return AckOut(ok=True, task_id=task_id)


@router.get("/task/{task_id}", response_model=Dict)
async def get_task_status(
        task_id: str,
        service: GoogleSheetsService = Depends(get_sheets_service)
):
    try:
        return await service.get_task_status(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/day/{date}")
async def day_breakdown(
    date: str,
    level: Literal["section", "category", "subcategory"] = "subcategory",
    zero_suppress: bool = False,
    include_month_summary: bool = False,
    include_comments: bool = True,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    try:
        return await service.day_breakdown(date, level, zero_suppress, include_month_summary, include_comments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/month/{ym}")
async def get_month_summary(
    ym: str,
    include_comments: bool = True,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    try:
        return await service.get_month_summary(ym, include_comments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/period/{start_date}/{end_date}")
async def period_expense_summary(
    start_date: str,
    end_date: str,
    level: Literal["section", "category", "subcategory"] = "subcategory",
    zero_suppress: bool = False,
    include_comments: bool = True,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, Any]:
    try:
        return await service.period_expense_summary(start_date, end_date, level, zero_suppress, include_comments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/month_totals/{ym}")
async def month_totals(
    ym: str,
    include_balances: bool = False,
    service: GoogleSheetsService = Depends(get_sheets_service)
) -> Dict[str, float]:
    try:
        return await service.month_totals(ym, include_balances)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/months_overview")
async def months_overview(service: GoogleSheetsService = Depends(get_sheets_service)) -> Dict[str, Dict[str, float]]:
    return await service.months_overview()


@router.post("/refresh")
async def refresh_data(service: GoogleSheetsService = Depends(get_sheets_service)) -> Dict[str, str]:
    try:
        await service.refresh_data()
        return {"status": "success", "message": "Data refreshed and cache invalidated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh data: {str(e)}")


@router.get("/meta", response_model=Dict)
async def get_metadata(service: GoogleSheetsService = Depends(get_sheets_service)):
    """
    Возвращает метаданные, сформированные из Google Sheets.
    """
    log.info("Fetching metadata from GoogleSheetsService")
    try:
        meta = service.meta  # meta — это словарь, возвращённый build_meta
        # log.info(f"Metadata fetched: date_cols={list(meta['date_cols'].keys())}")
        return meta
    except Exception as e:
        log.error(f"Failed to fetch metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch metadata: {str(e)}")
