"""End-to-end tests in SAMPLE_MODE: no services, no network, no credentials.

These are the reproducible feature tests the Sponsor Technology Explanation
points to: the run interface shape, real agent handoffs in the trace, the
Critic bouncing work, and the H-MEM engine changing a later answer after a
human decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.orchestrator import Orchestrator
from app.schemas import RunRequest

ROOT = Path(__file__).resolve().parents[1]
TRACE_FIELDS = {"timestamp", "run_id", "agent_name", "action", "input_summary", "output_summary",
                "target_agent", "model", "confidence", "retry_count", "status"}


@pytest.fixture()
def orch(tmp_path: Path) -> Orchestrator:
    cfg = Settings()
    cfg.sample_mode = True
    cfg.memory_dir = tmp_path / "memory"
    cfg.logs_dir = tmp_path / "logs"
    return Orchestrator(cfg)


def _run(orch: Orchestrator, run_id: str, query: str):
    return orch.run(RunRequest(run_id=run_id, input={"query": query}, options={"sample_mode": True}))


def _trace(orch: Orchestrator, run_id: str) -> list[dict]:
    p = orch.cfg.logs_dir / f"trace-{run_id}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_supplier_overlap_response_shape_and_trace(orch):
    r = _run(orch, "t-overlap", "Which suppliers do Woking, Guildford and Waverley share?")
    assert r.status == "success"
    assert r.log_file == "logs/trace-t-overlap.jsonl"
    assert r.trace_id == "trace-t-overlap"
    assert r.output.summary and r.output.recommendations and r.output.artifacts
    names = [a.name for a in r.agents]
    assert {"Router", "Researcher", "Resolver", "Memory", "Critic", "Writer"} <= set(names)
    events = _trace(orch, "t-overlap")
    assert all(TRACE_FIELDS <= set(e) for e in events)
    # real handoffs and at least one critique that rejected work and a retry
    assert any(e["agent_name"] == "Router" and e["target_agent"] == "Researcher" for e in events)
    assert any(e["agent_name"] == "Critic" and e["status"] == "rejected" for e in events)
    assert any(e["retry_count"] >= 1 for e in events)
    stats = next(a for a in r.output.artifacts if a["type"] == "run_stats")
    assert stats["presented"] > 100  # real shared suppliers exist in the published data
    assert stats["critic_bounces"] >= 1


def test_numbers_have_provenance(orch):
    r = _run(orch, "t-prov", "Which suppliers do Guildford and Waverley share?")
    table = next(a for a in r.output.artifacts if a.get("title", "").startswith("Shared suppliers"))
    assert table["count"] > 0
    for row in table["rows"]:
        assert row["a_provenance"] and row["b_provenance"]
        assert row["a_provenance"].split(":")[0] in ("wok", "gui", "wav")


def test_memory_changes_a_later_answer(orch):
    before = _run(orch, "t-1", "Which suppliers do Guildford and Waverley share?")
    stats_before = next(a for a in before.output.artifacts if a["type"] == "run_stats")
    rows_before = next(a for a in before.output.artifacts if a.get("title", "").startswith("Shared suppliers"))["rows"]
    assert not any(r["decision_id"] for r in rows_before)

    confirm = _run(orch, "t-2", "Confirm that 'Unit 4 Business Software Ltd' (Waverley) is the same supplier as 'Unit4 Business Software Ltd' (Guildford)")
    assert confirm.status == "success", getattr(confirm, "error", None)
    decision = next(a for a in confirm.output.artifacts if a["type"] == "decision")["decision"]
    assert decision["memory_id"].startswith("mem-")
    # the engine's own ledger recorded the create
    actions = [e.action for e in orch.memory.ledger.history(decision["memory_id"])]
    assert actions[0] == "create"

    after = _run(orch, "t-3", "Which suppliers do Guildford and Waverley share?")
    rows_after = next(a for a in after.output.artifacts if a.get("title", "").startswith("Shared suppliers"))["rows"]
    resolved = [r for r in rows_after if r["decision_id"] == decision["memory_id"]]
    assert len(resolved) == 1
    assert resolved[0]["status"] == "confirmed"
    assert "resolved using decision" in resolved[0]["notes"][0]
    stats_after = next(a for a in after.output.artifacts if a["type"] == "run_stats")
    assert stats_after["presented"] == stats_before["presented"] + 1
    assert f"resolved from remembered human decisions ({decision['memory_id']})" in after.output.summary
    # and the engine ledger now shows the read that the Memory agent made
    assert "read" in [e.action for e in orch.memory.ledger.history(decision["memory_id"])]


def test_contract_cliff_and_approval_gate(orch):
    r = _run(orch, "t-cliff", "Which contracts end within six months of vesting day?")
    assert r.status == "success"
    stats = next(a for a in r.output.artifacts if a["type"] == "run_stats")
    assert stats["total_hard_cliff_gbp"] > 0
    draft = next(a for a in r.output.artifacts if a["type"] == "draft")["draft"]
    assert draft["status"] == "pending" and draft["model"] == "sample-mode/template"
    assert "not sent" in draft["text"].lower()
    ok = _run(orch, "t-approve", f"Approve draft {draft['id']}")
    assert ok.status == "success" and "approved" in ok.output.summary
    assert orch.approvals.get(draft["id"])["status"] == "approved"


def test_policy_gap_cites_pages(orch):
    r = _run(orch, "t-policy", "Where do the Council Tax Support schemes differ between Woking and Guildford?")
    assert r.status == "success"
    grid = next(a for a in r.output.artifacts if a["type"] == "clause_grid")
    assert len(grid["differences"]) >= 3
    for row in grid["clauses"]:
        assert row["page"] and row["source_pdf"].endswith(".pdf")
    table = next(a for a in r.output.artifacts if a.get("synthetic"))
    assert all(row["label"] == "SYNTHETIC" for row in table["rows"])


def test_unsupported_request_is_structured_error(orch):
    r = _run(orch, "t-bad", "What is the weather in Guildford tomorrow?")
    assert r.status == "error"
    assert r.error.type == "UnsupportedRequest" and r.error.recoverable is True
    assert "supplier_overlap" in r.error.message


def test_http_interface(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "m"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "l"))
    import importlib
    import app.config as config
    importlib.reload(config)
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["sample_mode"] is True
    body = json.loads((ROOT / "input_examples" / "04_contract_cliff.json").read_text())
    resp = client.post("/run", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success" and data["run_id"] == "example-04"
    assert set(data) >= {"run_id", "status", "output", "agents", "trace_id", "log_file", "execution_time_seconds"}
