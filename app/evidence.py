"""Recorded live runs, read back from the committed logs (nothing is re-run).

Every live run committed in logs/ is a pair: response-<run_id>.json (the POST /run answer) and
trace-<run_id>.jsonl (what each agent did). This module lists them with the facts worth
checking first - which question, which model, how many signed receipts, how many Zetaris
queries, how many times the Critic sent work back - and pulls the headline results out of the
newest live day-one brief, so the web page can open with real results from a real live run
without typing a single number into the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.exports import export_path

LIVE_ID = re.compile(r"live-[0-9]{2}")
EXPORT_URL = re.compile(r"/export/([A-Za-z0-9_-]{1,80})/([a-z0-9-]+)\.csv")


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def live_response(logs_dir: Path, run_id: str) -> dict[str, Any] | None:
    if not LIVE_ID.fullmatch(run_id):
        return None
    p = logs_dir / f"response-{run_id}.json"
    if not p.is_file():
        return None
    resp = json.loads(p.read_text(encoding="utf-8"))
    _drop_missing_exports(resp.get("output", {}).get("artifacts", []), logs_dir)
    return resp


def _drop_missing_exports(artifacts: list[dict[str, Any]], logs_dir: Path) -> None:
    """A recorded run only offers a CSV download if that CSV was committed with it."""
    for a in artifacts:
        exp = a.get("export")
        if exp:
            m = EXPORT_URL.fullmatch(str(exp.get("url", "")))
            if not m or export_path(logs_dir, m.group(1), m.group(2)) is None:
                a.pop("export", None)
        if a.get("type") == "step_results":
            for s in a.get("steps", []):
                _drop_missing_exports(s.get("artifacts", []), logs_dir)


def summarise_run(logs_dir: Path, run_id: str) -> dict[str, Any] | None:
    resp = live_response(logs_dir, run_id)
    if resp is None:
        return None
    events = _read_trace(logs_dir / f"trace-{run_id}.jsonl")
    arts = resp.get("output", {}).get("artifacts", []) or []
    mode = next((a for a in arts if a.get("type") == "run_mode"), {})
    receipts = sorted({e["details"]["receipt_id"] for e in events if (e.get("details") or {}).get("receipt_id")})
    return {
        "run_id": run_id,
        "query": events[0].get("input_summary") if events else None,
        "started": events[0].get("timestamp") if events else None,
        "status": resp.get("status"),
        "flow": mode.get("flow"),
        "data_layer": mode.get("data_layer"),
        "model": mode.get("model"),
        "live": mode.get("sample_mode") is False,
        "seconds": resp.get("execution_time_seconds"),
        "trace_events": len(events),
        "zetaris_queries": sum(1 for e in events if e.get("action") == "query_data_layer"),
        "model_calls_with_receipts": len(receipts),
        "sent_back": sum(1 for e in events if e.get("status") in ("rejected", "needs_revision")),
        "planner_delegations": sum(1 for e in events if e.get("agent_name") == "Planner" and e.get("action") == "delegate"),
        "plan_source": next((e.get("details", {}).get("source") for e in events if e.get("agent_name") == "Planner" and e.get("action") == "plan"), None),
    }


def live_runs(logs_dir: Path) -> list[dict[str, Any]]:
    ids = sorted({m.group(0) for p in logs_dir.glob("response-live-*.json") if (m := LIVE_ID.fullmatch(p.stem[len("response-"):]))})
    runs = [summarise_run(logs_dir, i) for i in ids]
    return [r for r in runs if r]


def critic_record(logs_dir: Path, run_ids: list[str]) -> dict[str, Any]:
    """Across the recorded live runs: how many model drafts were written, and what the Critic sent back."""
    drafts, sent_back, reasons = 0, 0, []
    for rid in run_ids:
        for e in _read_trace(logs_dir / f"trace-{rid}.jsonl"):
            if e.get("agent_name") == "Writer" and e.get("action") == "draft" and e.get("model") and "template" not in str(e.get("model")):
                drafts += 1
            if e.get("agent_name") == "Critic" and e.get("action") == "critique_draft" and e.get("status") == "rejected":
                sent_back += 1
                reasons.append({"run_id": rid, "reason": str(e.get("output_summary", ""))[:220]})
    return {"model_drafts": drafts, "sent_back": sent_back, "reasons": reasons}


def headline(resp: dict[str, Any]) -> dict[str, Any] | None:
    """The day-one results a finance lead acts on, taken from a day-one brief response."""
    arts = resp.get("output", {}).get("artifacts", []) or []
    steps = next((a.get("steps", []) for a in arts if a.get("type") == "step_results"), None)
    if not steps:
        return None
    out: dict[str, Any] = {}
    for s in steps:
        if s.get("status") != "done":
            continue
        sa = s.get("artifacts", [])
        stats = next((a for a in sa if a.get("type") == "run_stats"), {}) or {}
        drafts = [a["draft"]["id"] for a in sa if a.get("type") == "draft" and a.get("draft")]
        tables = [a for a in sa if a.get("type") == "table"]
        if s["check"] == "contract_cliff":
            hard = tables[0] if tables else {}
            out["contracts"] = {"count": hard.get("count"), "value_gbp": stats.get("total_hard_cliff_gbp"), "window_days": stats.get("window_days"),
                                "shared_suppliers": stats.get("shared_suppliers_on_cliff"), "drafts": drafts, "councils": s.get("councils"),
                                "export": hard.get("export")}
        elif s["check"] == "supplier_overlap":
            queue = next((t for t in tables if "human decision" in t.get("title", "")), {})
            shared = next((t for t in tables if t.get("title", "").startswith("Shared suppliers")), {})
            mem = next((a for a in sa if a.get("type") == "memory"), {}) or {}
            out["suppliers"] = {"shared": stats.get("presented"), "spend_gbp": stats.get("shared_spend_gbp"), "awaiting_human": stats.get("needs_human"),
                                "recalled": sorted(d.get("memory_id") for d in (mem.get("decisions") or {}).values()), "councils": s.get("councils"),
                                "export": shared.get("export"), "queue_export": queue.get("export")}
        elif s["check"] == "policy_gap":
            grid = next((a for a in sa if a.get("type") == "clause_grid"), {}) or {}
            residents = next((t for t in tables if t.get("synthetic")), {}) or {}
            rows = residents.get("rows") or []
            out["policy"] = {"differ": len(grid.get("differences") or []), "clauses": len(grid.get("differences") or []) + len(grid.get("agreements") or []),
                             "synthetic_residents": len(rows), "synthetic_differ": sum(1 for r in rows if r.get("differs_between_councils")),
                             "drafts": drafts, "councils": s.get("councils")}
    return out or None


def evidence_index(logs_dir: Path) -> dict[str, Any]:
    runs = live_runs(logs_dir)
    briefs = [r for r in runs if r["flow"] == "day_one_brief" and r["status"] == "success"]
    head, source = None, None
    if briefs:
        source = briefs[-1]
        head = headline(live_response(logs_dir, source["run_id"]) or {})
    return {"runs": runs, "headline": head, "headline_run": source, "critic": critic_record(logs_dir, [r["run_id"] for r in runs])}
