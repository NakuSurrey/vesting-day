"""VESTING DAY - HTTP entry point.

GET  /health  -> {"status": "ok", "sample_mode": bool, ...}
POST /run     -> the HackOS run contract (see app/schemas.py)

Start with `python run.py` (binds 0.0.0.0:PORT, default 8000).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.orchestrator import Orchestrator
from app.schemas import RunRequest

app = FastAPI(title="VESTING DAY", version="0.1.0",
              description="Federates merging councils' spend, contract and policy data in place; remembers human decisions; drafts day-one actions under an approval gate.")
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(settings)
    return _orchestrator


@app.get("/health")
def health() -> dict:
    o = get_orchestrator()
    return {
        "status": "ok",
        "service": "vesting-day",
        "sample_mode": settings.effective_sample_mode(None),
        "memories": len(o.memory.store.all()),
        "pending_drafts": len(o.approvals.pending()),
        "councils": list((o.sources.get("councils") or {}).keys()),
    }


@app.post("/run")
def run(req: RunRequest) -> JSONResponse:
    result = get_orchestrator().run(req)
    return JSONResponse(content=result.model_dump(), status_code=200)


@app.get("/")
def root() -> dict:
    return {"service": "vesting-day", "run": "POST /run", "health": "GET /health", "docs": "/docs"}
