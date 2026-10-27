"""The web page and the routes it uses: a thin layer over POST /run.

GET / serves one self-contained page (no external scripts, styles or fonts, so it works with
no network). It drives the same POST /run anyone can curl, reads the run's trace through
GET /trace/{run_id}, and can clear the shared demo memory through POST /demo/reset.
"""

from __future__ import annotations

import importlib
import re

import pytest
from fastapi.testclient import TestClient

GW_Q = "Which suppliers do Guildford and Waverley share?"
CONFIRM_Q = "Confirm that 'Unit 4 Business Software Ltd' (Waverley) is the same supplier as 'Unit4 Business Software Ltd' (Guildford)"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "m"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "l"))
    import app.config as config
    importlib.reload(config)
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def _run(client, run_id: str, q: str) -> dict:
    r = client.post("/run", json={"run_id": run_id, "input": {"query": q}})
    assert r.status_code == 200
    return r.json()


def _stats(resp: dict) -> dict:
    return next(a for a in resp["output"]["artifacts"] if a["type"] == "run_stats")


def test_page_is_served_and_self_contained(client) -> None:
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "VESTING DAY" in html and "Solving Fragmented Intelligence" in html
    assert "/run" in html and "/trace/" in html and "/demo/reset" in html
    # nothing loaded from the internet: no external scripts, stylesheets or fonts
    assert not re.search(r"<script[^>]+src=", html, re.I)
    assert not re.search(r"<link[^>]+href=", html, re.I)
    assert "@import" not in html and "fonts.googleapis" not in html
    assert all(ord(c) < 128 for c in html), "page source must be plain ASCII"
    # a link checker's HEAD request gets the same answer as GET, with no body
    for path in ("/", "/health", "/evidence", "/docs"):
        h = client.head(path)
        assert h.status_code == 200 and h.content == b"", (path, h.status_code)
    assert client.head("/").headers["content-type"].startswith("text/html")


def test_api_index_lists_the_routes(client) -> None:
    j = client.get("/api").json()
    assert j["ui"] == "GET /" and j["run"] == "POST /run" and j["trace"] == "GET /trace/{run_id}"


def test_trace_route_returns_the_agents_steps(client) -> None:
    resp = _run(client, "web-t1", "Which contracts end within six months of vesting day?")
    assert resp["status"] == "success"
    t = client.get("/trace/web-t1").json()
    assert t["trace_file"] == "logs/trace-web-t1.jsonl"
    agents = {e["agent_name"] for e in t["events"]}
    assert {"Router", "Researcher", "Critic", "Writer", "ApprovalGate"} <= agents
    assert any(e["action"] == "query_data_layer" for e in t["events"])


@pytest.mark.parametrize("bad, code", [("..%2F..%2Fetc", 400), ("a.b", 400), ("no-such-run", 404)])
def test_trace_route_rejects_bad_or_unknown_ids(client, bad: str, code: int) -> None:
    assert client.get(f"/trace/{bad}").status_code in (code, 404)


def test_memory_demo_over_http_then_reset(client) -> None:
    assert client.post("/demo/reset").json()["memories"] == 0
    before = _run(client, "web-d1", GW_Q)
    confirm = _run(client, "web-d2", CONFIRM_Q)
    after = _run(client, "web-d3", GW_Q)
    assert "mem-1" in confirm["output"]["summary"]
    assert _stats(after)["presented"] == _stats(before)["presented"] + 1
    assert _stats(after)["needs_human"] == _stats(before)["needs_human"] - 1
    assert "mem-1" in after["output"]["summary"]
    assert client.get("/health").json()["memories"] >= 1
    client.post("/demo/reset")
    assert client.get("/health").json()["memories"] == 0
    again = _run(client, "web-d4", GW_Q)
    assert _stats(again)["presented"] == _stats(before)["presented"]      # the decision is gone after a reset
