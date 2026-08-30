from fastapi import FastAPI
from pydantic import BaseModel
from agent import check_goal

app = FastAPI(title="Goal Checker Agent")

class GoalRequest(BaseModel):
    goal: str

@app.post("/check-goal")        # <-- та самая "ручка"
def check(req: GoalRequest):
    return check_goal(req.goal)

@app.get("/health")
def health():
    return {"status": "ok"}