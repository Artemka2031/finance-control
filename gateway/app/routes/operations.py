# gateway/app/routes/operations.py

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from ..services.sheets import SheetsService

router = APIRouter()

class ExpenseIn(BaseModel):
    date: str = Field(..., example='01.05.25')
    chapter: str
    category: str
    amount: float
    comment: str | None = None

class AckOut(BaseModel):
    ok: bool = True

@router.post('/expense', response_model=AckOut)
async def add_expense(payload: ExpenseIn, request: Request):
    """
    Добавление расхода: сохраняет запись в Google Sheets и инвалидирует кэш.
    """
    redis = request.app.state.redis
    service = SheetsService(redis)
    try:
        await service.add_expense(
            date=payload.date,
            chapter=payload.chapter,
            category=payload.category,
            amount=payload.amount,
            comment=payload.comment,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AckOut()
