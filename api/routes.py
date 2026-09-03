"""HTTP-маршруты каталога нормативных требований."""

import logging

from fastapi import APIRouter, HTTPException, Query

import catalog
import schemas

log = logging.getLogger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _handle(func, *args, **kwargs):
    """Переводит ошибки каталога в осмысленные коды ответа."""
    try:
        return func(*args, **kwargs)
    except catalog.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except catalog.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ------------------------------- чтение -------------------------------------


@router.get("/tree")
def get_tree(include_archived: bool = Query(False, description="Показывать архив")):
    """Весь каталог: приказы → пункты → правила → атрибуты и примеры."""
    return _handle(catalog.build_tree, include_archived)


@router.get("/check-targets")
def get_check_targets(include_archived: bool = Query(False)):
    return {"targets": _handle(catalog.list_check_targets, include_archived)}


# ------------------------------- приказы ------------------------------------


@router.post("/orders", status_code=201)
def post_order(body: schemas.OrderCreate):
    return _handle(
        catalog.create_order, body.number, body.title, body.date, body.orderId
    )


@router.patch("/orders/{order_id:path}")
def patch_order(order_id: str, body: schemas.OrderUpdate):
    return _handle(catalog.update_order, order_id, **body.model_dump(exclude_none=True))


@router.post("/orders/{order_id:path}/status")
def post_order_status(order_id: str, body: schemas.StatusRequest):
    return _handle(catalog.set_order_status, order_id, body.status)


@router.delete("/orders/{order_id:path}")
def delete_order(order_id: str):
    return _handle(catalog.delete_order, order_id)


# -------------------------------- пункты ------------------------------------


@router.post("/clauses", status_code=201)
def post_clause(body: schemas.ClauseCreate):
    return _handle(catalog.create_clause, body.orderId, body.code, body.text, body.clauseId)


@router.patch("/clauses/{clause_id:path}")
def patch_clause(clause_id: str, body: schemas.ClauseUpdate):
    return _handle(catalog.update_clause, clause_id, **body.model_dump(exclude_none=True))


@router.post("/clauses/{clause_id:path}/status")
def post_clause_status(clause_id: str, body: schemas.StatusRequest):
    return _handle(catalog.set_clause_status, clause_id, body.status)


@router.delete("/clauses/{clause_id:path}")
def delete_clause(clause_id: str):
    return _handle(catalog.delete_clause, clause_id)


# ------------------------------- правила ------------------------------------


@router.post("/rules", status_code=201)
def post_rule(body: schemas.RuleCreate):
    return _handle(
        catalog.create_rule,
        body.clauseId,
        body.type,
        body.description,
        body.checkInstruction,
        body.targets,
        body.ruleId,
    )


@router.patch("/rules/{rule_id:path}")
def patch_rule(rule_id: str, body: schemas.RuleUpdate):
    fields = body.model_dump(exclude_none=True)
    if "checkInstruction" in fields:
        fields["check_instruction"] = fields.pop("checkInstruction")
    return _handle(catalog.update_rule, rule_id, **fields)


@router.put("/rules/{rule_id:path}/targets")
def put_rule_targets(rule_id: str, body: schemas.RuleTargets):
    return {"targets": _handle(catalog.set_rule_targets, rule_id, body.targets)}


@router.post("/rules/{rule_id:path}/status")
def post_rule_status(rule_id: str, body: schemas.StatusRequest):
    return _handle(catalog.set_rule_status, rule_id, body.status)


@router.delete("/rules/{rule_id:path}")
def delete_rule(rule_id: str):
    return _handle(catalog.delete_rule, rule_id)


# ------------------------------- атрибуты -----------------------------------


@router.post("/check-targets", status_code=201)
def post_check_target(body: schemas.CheckTargetCreate):
    return _handle(catalog.create_check_target, body.name, body.description)


@router.patch("/check-targets/{name:path}")
def patch_check_target(name: str, body: schemas.CheckTargetUpdate):
    return _handle(catalog.update_check_target, name, body.description)


@router.post("/check-targets/{name:path}/status")
def post_check_target_status(name: str, body: schemas.StatusRequest):
    return _handle(catalog.set_check_target_status, name, body.status)


@router.delete("/check-targets/{name:path}")
def delete_check_target(name: str):
    return _handle(catalog.delete_check_target, name)


# ------------------------------- примеры ------------------------------------


@router.post("/examples", status_code=201)
def post_example(body: schemas.ExampleCreate):
    return _handle(
        catalog.create_example, body.ruleId, body.text, body.isViolation, body.exampleId
    )


@router.patch("/examples/{example_id:path}")
def patch_example(example_id: str, body: schemas.ExampleUpdate):
    fields = body.model_dump(exclude_none=True)
    if "isViolation" in fields:
        fields["is_violation"] = fields.pop("isViolation")
    return _handle(catalog.update_example, example_id, **fields)


@router.delete("/examples/{example_id:path}")
def delete_example(example_id: str):
    return _handle(catalog.delete_example, example_id)
