"""HTTP-интерфейс агента проверки целей."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import graph
from agent import check_goal
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

    Дубликаты написаний атрибутов и атрибуты без описания делают проверку
    целей молча неполной, поэтому это тоже «не готов», а не предупреждение.
    """
    neo4j_ok = graph.verify_connectivity()
    targets = 0
    problems: list[str] = []
    diagnostics: dict = {}

    if neo4j_ok:
        try:
            targets = len(graph.get_check_targets())
            diagnostics = graph.diagnose()
            problems = diagnostics["problems"]
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось прочитать словарь атрибутов: %s", exc)
            neo4j_ok = False

    if not targets:
        problems = ["Словарь атрибутов (:CheckTarget) пуст — граф не заполнен"] + problems

    ready_now = neo4j_ok and bool(targets) and not problems
    payload = {
        "status": "ready" if ready_now else "not_ready",
        "neo4j": neo4j_ok,
        "check_targets": targets,
        "problems": problems,
        "diagnostics": diagnostics,
    }
    if ready_now:
        return payload
    log.warning("Граф не готов к проверкам: %s", "; ".join(problems) or "Neo4j недоступен")
    return JSONResponse(status_code=503, content=payload)
