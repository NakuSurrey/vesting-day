"""VESTING DAY - HTTP entry point.

GET  /                  -> the web page: ask a question, watch the agents work (a thin layer over POST /run)
GET  /health            -> {"status": "ok", "sample_mode": bool, ...}
POST /run               -> run the agent on one request (see app/schemas.py)
GET  /trace/{run_id}    -> the run's trace events (logs/trace-<run_id>.jsonl)
GET  /export/{run_id}/{name}.csv -> a full action list from that run as CSV (logs/export-<run_id>-<name>.csv)
GET  /evidence          -> the recorded live runs committed in logs/, with headline results (nothing is re-run)
GET  /evidence/{run_id} -> one recorded live run's response
POST /demo/reset        -> clear H-MEM decisions and held drafts (the shared demo memory)
GET  /api               -> this list as JSON

Start with `uv run python run.py` (binds 0.0.0.0:PORT, default 8000).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.agents.approval import reset_memory_dir
from app.config import settings
from app.evidence import evidence_index, live_response
from app.exports import export_path
from app.orchestrator import Orchestrator
from app.prerender import prerender
from app.schemas import RunRequest

app = FastAPI(title="VESTING DAY", version="0.1.0",
              description="Federates merging councils' spend, contract and policy data in place; remembers human decisions; drafts day-one actions under an approval gate.")
_orchestrator: Orchestrator | None = None
_lock = threading.Lock()          # one run at a time: H-MEM and the approval store are shared state
_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_PAGE = Path(__file__).resolve().parent / "web" / "index.html"


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
    with _lock:
        result = get_orchestrator().run(req)
    return JSONResponse(content=result.model_dump(), status_code=200)


@app.get("/trace/{run_id}")
def trace(run_id: str) -> dict:
    if not _RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="run_id may contain only letters, digits, '-' and '_'")
    path = get_orchestrator().cfg.logs_dir / f"trace-{run_id}.jsonl"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no trace for run_id {run_id}")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"run_id": run_id, "trace_file": f"logs/{path.name}", "events": events}


@app.get("/export/{run_id}/{name}.csv")
def export_csv(run_id: str, name: str) -> FileResponse:
    if not _RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="run_id may contain only letters, digits, '-' and '_'")
    path = export_path(get_orchestrator().cfg.logs_dir, run_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no export {name} for run_id {run_id}")
    return FileResponse(path, media_type="text/csv", filename=f"vesting-day-{run_id}-{name}.csv")


@app.get("/evidence")
def evidence() -> dict:
    """The recorded live runs (Zetaris + Nemotron via Nightshift) committed in logs/, read back as they are."""
    return evidence_index(get_orchestrator().cfg.logs_dir)


@app.get("/evidence/{run_id}")
def evidence_run(run_id: str) -> dict:
    resp = live_response(get_orchestrator().cfg.logs_dir, run_id)
    if resp is None:
        raise HTTPException(status_code=404, detail=f"no recorded live run {run_id}")
    return resp


@app.post("/demo/reset")
def demo_reset() -> dict:
    """Clear stored decisions and held drafts so the memory demo starts from nothing."""
    global _orchestrator
    with _lock:
        reset_memory_dir(get_orchestrator().cfg.memory_dir)
        _orchestrator = None      # rebuilt on the next request with empty H-MEM and approval stores
    return {"status": "ok", "memories": 0, "pending_drafts": 0}


@app.get("/", response_class=HTMLResponse)
def page() -> HTMLResponse:
    html = _PAGE.read_text(encoding="utf-8")
    try:
        html = prerender(html, evidence_index(settings.logs_dir))   # results readable without JavaScript too
    except Exception:   # the script still fills the page from GET /evidence; never fail the page over this
        pass
    return HTMLResponse(html)


@app.get("/api")
def api_index() -> dict:
    return {"service": "vesting-day", "ui": "GET /", "run": "POST /run", "health": "GET /health",
            "trace": "GET /trace/{run_id}", "export": "GET /export/{run_id}/{name}.csv", "evidence": "GET /evidence",
            "evidence_run": "GET /evidence/{run_id}", "reset_demo_memory": "POST /demo/reset", "docs": "/docs"}
