"""HTTP-маршруты каталога нормативных требований.

Узлы адресуются по nodeId (elementId Neo4j): он есть всегда, в отличие от
бизнес-ключей, которых может не быть у ранее заведённых данных.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

import catalog
import diagnostics
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


@router.get("/clauses")
def get_clauses_flat():
    """Плоский список пунктов — для выбора родителя и перекрёстных ссылок."""
    return {"clauses": _handle(catalog.list_clauses_flat)}


@router.get("/diagnostics")
def get_diagnostics():
    """Развёрнутая диагностика графа с указанием конкретных узлов."""
    return _handle(diagnostics.collect)


# --------------------- операции над произвольным узлом ----------------------


@router.get("/nodes/{node_id}")
def get_node(node_id: str):
    """Все свойства узла — для редактора свойств."""
    return _handle(catalog.get_node, node_id)


@router.patch("/nodes/{node_id}/properties")
def patch_node_properties(node_id: str, body: schemas.PropertiesRequest):
    """Правка произвольных свойств. null в значении удаляет свойство."""
    return _handle(catalog.update_properties, node_id, dict(body.properties))


@router.post("/nodes/{node_id}/status")
def post_node_status(node_id: str, body: schemas.StatusRequest):
    return _handle(catalog.set_status, node_id, body.status)


@router.get("/nodes/{node_id}/descendants")
def get_descendants(node_id: str):
    """Что будет удалено вместе с узлом."""
    return _handle(catalog.count_descendants, node_id)


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str):
    return _handle(catalog.delete_node, node_id)


# ------------------------------- создание -----------------------------------


@router.post("/orders", status_code=201)
def post_order(body: schemas.OrderCreate):
    return _handle(catalog.create_order, body.number, body.title, body.date, body.orderId)


@router.post("/clauses", status_code=201)
def post_clause(body: schemas.ClauseCreate):
    return _handle(catalog.create_clause, body.orderNodeId, body.code, body.text, body.clauseId)


@router.post("/rules", status_code=201)
def post_rule(body: schemas.RuleCreate):
    return _handle(
        catalog.create_rule, body.clauseNodeId, body.type, body.description,
        body.checkInstruction, body.targets, body.ruleId,
    )


@router.post("/examples", status_code=201)
def post_example(body: schemas.ExampleCreate):
    return _handle(catalog.create_example, body.ruleNodeId, body.text,
                   body.isViolation, body.exampleId)


@router.post("/check-targets", status_code=201)
def post_check_target(body: schemas.CheckTargetCreate):
    return _handle(catalog.create_check_target, body.name, body.description)


# -------------------------------- связи -------------------------------------


@router.put("/rules/{node_id}/targets")
def put_rule_targets(node_id: str, body: schemas.RuleTargets):
    return {"targets": _handle(catalog.set_rule_targets, node_id, body.targets)}


@router.put("/clauses/{node_id}/references")
def put_clause_references(node_id: str, body: schemas.ClauseReferences):
    return {"references": _handle(catalog.set_clause_references, node_id, body.references)}


@router.post("/clauses/{node_id}/move")
def post_move_clause(node_id: str, body: schemas.MoveRequest):
    return _handle(catalog.move_clause, node_id, body.parentNodeId)


@router.post("/rules/{node_id}/move")
def post_move_rule(node_id: str, body: schemas.MoveRequest):
    return _handle(catalog.move_rule, node_id, body.parentNodeId)


# ------------------------------- ремонт -------------------------------------


@router.post("/repair-identifiers")
def post_repair_identifiers():
    """Проставляет недостающие orderId / clauseId / ruleId / exampleId и статусы."""
    return _handle(catalog.repair_identifiers)
