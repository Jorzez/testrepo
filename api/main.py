"""HTTP-интерфейс агента проверки целей."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import diagnostics
import graph
import schemas
from agent import check_goal, check_goals
from routes import router as catalog_router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Недоступность Neo4j на старте не должна ронять контейнер:
    # оркестратор перезапустит зависимости, а /ready покажет реальное состояние.
    if graph.verify_connectivity():
        log.info("Соединение с Neo4j установлено")
    else:
        log.warning("Neo4j недоступен на старте, повторим при первом запросе")
    yield
    graph.close_driver()


app = FastAPI(title="Goal Checker Agent", version="1.0.0", lifespan=lifespan)

# Фронтенд отдаётся с другого порта (3000), поэтому нужен CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ],
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["*"],
)

# CRUD над приказами, пунктами, правилами, атрибутами и примерами.
app.include_router(catalog_router)


class GoalRequest(BaseModel):
    goal: str = Field(..., description="Формулировка цели для проверки")


@app.post("/check-goal")
def check(req: GoalRequest):
    """Проверка цели на соответствие действующим приказам."""
    return check_goal(req.goal)


MAX_BATCH = int(os.getenv("MAX_GOALS_PER_REQUEST", "200"))


@app.post("/check-goals")
def check_many(items: list[schemas.GoalItem] = Body(..., description="Массив целей")):
    """Пакетная проверка целей.

    Вход — массив объектов вида {"goal": "...", "id": "..."}. Порядок ответов
    совпадает с порядком входа, id возвращается как передан (или null).
    Обращения к модели идут параллельно; словарь атрибутов читается один раз.
    """
    if len(items) > MAX_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"За один раз можно проверить не более {MAX_BATCH} целей, передано {len(items)}",
        )
    return check_goals([item.model_dump() for item in items])


@app.get("/check-targets")
def check_targets():
    """Словарь проверяемых атрибутов из графа (полезно для отладки и UI)."""
    return {"targets": graph.get_check_targets()}


@app.get("/health")
def health():
    """Liveness: процесс жив."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: зависимости доступны, граф заполнен и внутренне непротиворечив.

    Дубликаты написаний, атрибуты без описания, правила без атрибутов и узлы
    без идентификаторов делают проверку целей молча неполной, поэтому это
    тоже «не готов», а не предупреждение. Развёрнутый разбор с указанием
    конкретных узлов — в /catalog/diagnostics.
    """
    if not graph.verify_connectivity():
        return JSONResponse(status_code=503, content={
            "status": "not_ready", "neo4j": False, "check_targets": 0,
            "problems": ["Neo4j недоступен"], "diagnostics": {},
        })

    try:
        report = diagnostics.collect()
    except Exception as exc:  # noqa: BLE001
        log.warning("Диагностика не выполнилась: %s", exc)
        return JSONResponse(status_code=503, content={
            "status": "not_ready", "neo4j": True, "check_targets": 0,
            "problems": [f"Не удалось прочитать граф: {exc}"], "diagnostics": {},
        })

    payload = {
        "status": "ready" if report["ready"] else "not_ready",
        "neo4j": True,
        "check_targets": report["check_targets"],
        "problems": report["problems"],
        "diagnostics": report,
    }
    if report["ready"]:
        return payload
    log.warning("Граф не готов к проверкам: %s", "; ".join(report["problems"]))
    return JSONResponse(status_code=503, content=payload)
