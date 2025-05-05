from pydantic import BaseModel, Field

# Модели для входных данных
class ExpenseIn(BaseModel):
    date: str = Field(..., examples=["01.05.25"])
    chapter: str = Field(..., alias="sec_code")
    category: str = Field(..., alias="cat_code")
    subcategory: str = Field(..., alias="sub_code")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class IncomeIn(BaseModel):
    date: str = Field(..., examples=["01.05.25"])
    category: str = Field(..., alias="cat_code")
    amount: float
    comment: str | None = None

    class Config:
        populate_by_name = True

class CreditorIn(BaseModel):
    creditor_name: str = Field(..., alias="cred_code")
    date: str = Field(..., examples=["01.05.25"])
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