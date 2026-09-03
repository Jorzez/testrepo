"""Схемы запросов для CRUD-эндпоинтов каталога."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["active", "archived"]
RuleType = Literal["PROHIBITION", "REQUIREMENT"]


class StatusRequest(BaseModel):
    status: Status


class PropertiesRequest(BaseModel):
    """Произвольные свойства узла. null удаляет свойство."""

    properties: dict[str, Any]


class OrderCreate(BaseModel):
    number: str = Field(..., min_length=1, max_length=100, description="Номер приказа, например ПР-01")
    title: str = Field(..., min_length=1, max_length=500)
    date: Optional[str] = Field(None, description="Дата в формате YYYY-MM-DD")
    orderId: Optional[str] = Field(None, description="Идентификатор; по умолчанию из номера")


class ClauseCreate(BaseModel):
    orderNodeId: str
    code: str = Field(..., min_length=1, max_length=50, description="Номер пункта, например 3.1")
    text: str = Field(..., min_length=1, max_length=8000)
    clauseId: Optional[str] = None


class RuleCreate(BaseModel):
    clauseNodeId: str
    type: RuleType
    description: str = Field(..., min_length=1, max_length=4000)
    checkInstruction: str = Field("", max_length=4000)
    targets: list[str] = Field(default_factory=list)
    ruleId: Optional[str] = None


class ExampleCreate(BaseModel):
    ruleNodeId: str
    text: str = Field(..., min_length=1, max_length=4000)
    isViolation: bool
    exampleId: Optional[str] = None


class CheckTargetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=4000)


class RuleTargets(BaseModel):
    targets: list[str]


class ClauseReferences(BaseModel):
    references: list[str] = Field(default_factory=list, description="nodeId пунктов")


class MoveRequest(BaseModel):
    parentNodeId: str = Field(..., description="nodeId нового родителя")
