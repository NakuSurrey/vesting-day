"""Action lists as CSV, and recorded live runs read back from the committed logs.

Every table an answer shows is written in full as CSV next to the run's trace (the JSON keeps
short preview rows), and GET /export serves it. GET /evidence lists the live runs committed in
logs/ with the facts worth checking first and the headline results of the newest live brief;
nothing is re-run and no number is typed into the page.
"""

from __future__ import annotations

import csv
import importlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "m"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "l"))
    import app.config as config
    importlib.reload(config)
    import app.main as main
    importlib.reload(main)
    c = TestClient(main.app)
    c.logs = tmp_path / "l"
    return c


def _tables(resp: dict) -> list[dict]:
    return [a for a in resp["output"]["artifacts"] if a["type"] == "table"]


def test_full_contract_list_is_written_and_served_as_csv(client) -> None:
    r = client.post("/run", json={"run_id": "x-cliff", "input": {"query": "Which contracts end within six months of vesting day?"}}).json()
    assert r["status"] == "success"
    hard = _tables(r)[0]
    assert hard["count"] == 173 and len(hard["rows"]) == 80                 # the JSON keeps a preview
    assert "_all_rows" not in json.dumps(r)                                  # the full list never bloats the response
    exp = hard["export"]
    assert exp["rows"] == 173 and exp["url"].startswith("/export/x-cliff/")
    assert exp["file"].startswith("logs/exports/x-cliff/")
    path = client.logs / "exports" / "x-cliff" / Path(exp["file"]).name
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 173 and {"council", "supplier_raw", "end_date", "provenance_id"} <= set(rows[0])
    got = client.get(exp["url"])
    assert got.status_code == 200 and got.headers["content-type"].startswith("text/csv")
    assert got.content.decode("utf-8-sig").count("\n") == 174              # header + 173 contracts


def test_brief_exports_every_check_table_and_bad_names_are_refused(client) -> None:
    r = client.post("/run", json={"run_id": "x-brief", "input": {"query": "What are the biggest risks on vesting day?"}}).json()
    steps = next(a for a in r["output"]["artifacts"] if a["type"] == "step_results")["steps"]
    exports = [t["export"] for s in steps for t in s["artifacts"] if t.get("type") == "table" and t.get("export")]
    names = [e["url"].rsplit("/", 1)[1] for e in exports]
    assert any(n.startswith("contract-cliff-hard-cliff") for n in names) and any(n.startswith("supplier-overlap-candidates-needing") for n in names)
    queue = next(e for e in exports if "candidates-needing" in e["url"])
    assert queue["rows"] == 217                                              # the whole human queue, not the 40-row preview
    assert any("synthetic" in n for n in names)                              # the residents file says SYNTHETIC in its name
    assert client.get("/export/x-brief/..%2F..%2Fsecret.csv").status_code == 404
    assert client.get("/export/x-brief/Not_A_Name.csv").status_code == 404
    assert client.get("/export/bad%20id/contract.csv").status_code == 400


def test_evidence_lists_recorded_live_runs_without_rerunning(client) -> None:
    client.logs.mkdir(parents=True, exist_ok=True)
    for n in ("01", "03"):
        for f in (f"response-live-{n}.json", f"trace-live-{n}.jsonl"):
            shutil.copy(REPO / "logs" / f, client.logs / f)
    ev = client.get("/evidence").json()
    runs = {r["run_id"]: r for r in ev["runs"]}
    assert set(runs) == {"live-01", "live-03"}
    one = runs["live-01"]
    assert one["live"] is True and one["flow"] == "supplier_overlap" and one["query"].startswith("Which suppliers")
    assert one["model_calls_with_receipts"] >= 1 and one["zetaris_queries"] >= 1 and one["sent_back"] >= 1
    assert ev["critic"]["sent_back"] >= 2 and "confirmed" in ev["critic"]["reasons"][0]["reason"]
    assert ev["headline"] is None                                            # no live day-one brief in this folder
    resp = client.get("/evidence/live-03").json()
    assert resp["run_id"] == "live-03" and resp["status"] == "success"
    assert client.get("/evidence/live-99").status_code == 404
    assert client.get("/evidence/web-123").status_code == 404                 # only recorded live runs are served here
    assert client.get("/trace/live-03").status_code == 200


def test_headline_comes_from_the_newest_live_brief(client) -> None:
    client.logs.mkdir(parents=True, exist_ok=True)
    r = client.post("/run", json={"run_id": "live-09", "input": {"query": "What are the biggest risks on vesting day?"}}).json()
    (client.logs / "response-live-09.json").write_text(json.dumps(r), encoding="utf-8")
    ev = client.get("/evidence").json()
    h = ev["headline"]
    assert ev["headline_run"]["run_id"] == "live-09"
    assert h["contracts"]["count"] == 173 and round(h["contracts"]["value_gbp"]) == 22671525 and h["contracts"]["shared_suppliers"] == 45
    assert h["suppliers"]["shared"] == 228 and h["suppliers"]["awaiting_human"] == 217
    assert h["policy"]["differ"] == 4 and h["policy"]["clauses"] == 9 and h["policy"]["synthetic_differ"] == 4
    assert h["contracts"]["export"]["rows"] == 173                           # its CSV is next to it, so it is offered
    (client.logs / "exports" / "live-09" / Path(h["contracts"]["export"]["file"]).name).unlink()
    assert client.get("/evidence").json()["headline"]["contracts"]["export"] is None   # a missing CSV is not offered


def test_page_has_the_results_band_and_recorded_runs(client) -> None:
    html = client.get("/").text
    for needle in ('id="results"', 'id="runsCard"', "loadEvidence()", "/evidence", "replayRun", "Download all rows", "no number is typed into this page"):
        assert needle in html
