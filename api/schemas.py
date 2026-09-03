"""Схемы запросов для CRUD-эндпоинтов каталога."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["active", "archived"]
RuleType = Literal["PROHIBITION", "REQUIREMENT"]


class StatusRequest(BaseModel):
    status: Status


class OrderCreate(BaseModel):
    number: str = Field(..., min_length=1, max_length=100, description="Номер приказа, например ПР-01")
    title: str = Field(..., min_length=1, max_length=500)
    date: Optional[str] = Field(None, description="Дата в формате YYYY-MM-DD")
    orderId: Optional[str] = Field(None, description="Идентификатор; по умолчанию из номера")


class OrderUpdate(BaseModel):
    number: Optional[str] = Field(None, min_length=1, max_length=100)
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    date: Optional[str] = None


class ClauseCreate(BaseModel):
    orderId: str
    code: str = Field(..., min_length=1, max_length=50, description="Номер пункта, например 3.1")
    text: str = Field(..., min_length=1, max_length=4000)
    clauseId: Optional[str] = None


class ClauseUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    text: Optional[str] = Field(None, min_length=1, max_length=4000)


class RuleCreate(BaseModel):
    clauseId: str
    type: RuleType
    description: str = Field(..., min_length=1, max_length=2000)
    checkInstruction: str = Field("", max_length=2000)
    targets: list[str] = Field(default_factory=list)
    ruleId: Optional[str] = None


class RuleUpdate(BaseModel):
    type: Optional[RuleType] = None
    description: Optional[str] = Field(None, min_length=1, max_length=2000)
    checkInstruction: Optional[str] = Field(None, max_length=2000)


class RuleTargets(BaseModel):
    targets: list[str]


class CheckTargetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)


class CheckTargetUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=2000)


class ExampleCreate(BaseModel):
    ruleId: str
    text: str = Field(..., min_length=1, max_length=2000)
    isViolation: bool
    exampleId: Optional[str] = None


class ExampleUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=2000)
    isViolation: Optional[bool] = None
