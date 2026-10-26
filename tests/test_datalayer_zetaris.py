"""Live data layer: the real Zetaris REST answer shape, checked against SAMPLE_MODE.

Zetaris answers {"headers": [...], "data": [[...]], "total": n} with every value as text
(seen on the live server). A fake Zetaris here runs the federated SQL over three separate
SQLite sources - one per council, like the three registered datasources - and answers in
that exact shape. Every Researcher query must then give the same rows, with the same types,
live as it does in SAMPLE_MODE.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.datalayer import DataLayerError, LocalDataLayer, ZetarisDataLayer, _rows_from_payload
from app.agents.researcher import ResearcherAgent

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"
SOURCES = {"woking_pg": "Woking", "guildford_pg": "Guildford", "waverley_pg": "Waverley"}
COUNCILS = ["Woking", "Guildford", "Waverley"]


def test_real_answer_shape_from_the_live_server() -> None:
    # pasted from the live Zetaris on 26 Oct 2026
    payload = {"headers": ["council", "n"], "data": [["Woking", "9718"]], "total": 1, "timeUsed": 242}
    assert _rows_from_payload(payload) == [{"council": "Woking", "n": "9718"}]


def test_numbers_become_numbers_and_codes_stay_text() -> None:
    payload = {
        "headers": ["council", "rows_published", "total_gbp", "payment_to", "supplier_company_number", "source_row"],
        "data": [["Woking", "9718", "64974729.21", "2026-04-30 00:00:00", "01234567", "12"], ["Waverley", "0", "", None, "", "3"]],
        "total": 2,
    }
    assert _rows_from_payload(payload) == [
        {"council": "Woking", "rows_published": 9718, "total_gbp": 64974729.21, "payment_to": "2026-04-30",
         "supplier_company_number": "01234567", "source_row": "12"},
        {"council": "Waverley", "rows_published": 0, "total_gbp": None, "payment_to": None,
         "supplier_company_number": None, "source_row": "3"},
    ]


def _fake_zetaris(local: LocalDataLayer, cap: int | None = None):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    for src, council in SOURCES.items():
        conn.execute(f"ATTACH DATABASE ':memory:' AS {src}")
        for table in ("spend", "contracts", "policy_clause"):
            info = local.conn.execute(f"PRAGMA table_info({table})").fetchall()
            conn.execute(f"CREATE TABLE {src}.{table} ({', '.join(f'{c[1]} {c[2]}' for c in info)})")
            rows = local.conn.execute(f"SELECT * FROM {table} WHERE council = ?", (council,)).fetchall()
            conn.executemany(f"INSERT INTO {src}.{table} VALUES ({', '.join('?' for _ in info)})", [tuple(r) for r in rows])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1.0/sql-editor/sqls/run"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["X-Org-ID"] == "1"
        assert request.headers["X-Request-ID"]
        body = json.loads(request.content)
        assert body["source"] == "SqlEditor" and body["queryId"]
        cur = conn.execute(body["sql"])
        headers = [d[0] for d in cur.description]
        data = [[None if v is None else str(v) for v in r] for r in cur.fetchall()]
        total = len(data)
        data = data[: min(body["limit"], cap or body["limit"])]
        return httpx.Response(200, json={"headers": headers, "data": data, "total": total, "timeUsed": 1})

    return handler


def _researcher(layer) -> ResearcherAgent:
    ctx = SimpleNamespace(data=layer, agents_used={}, tracer=SimpleNamespace(log=lambda **kw: None))
    return ResearcherAgent(ctx)


def _live(local: LocalDataLayer, cap: int | None = None) -> ZetarisDataLayer:
    layer = ZetarisDataLayer("http://zetaris.test/api/v1.0", "1", "test-key")
    layer._client = httpx.Client(transport=httpx.MockTransport(_fake_zetaris(local, cap)))
    return layer


def _canon(rows: list[dict]) -> list[str]:
    # json keeps 9718 and 9718.0 apart, so this checks types as well as values
    return sorted(json.dumps(r, sort_keys=True) for r in rows)


@pytest.fixture(scope="module")
def local() -> LocalDataLayer:
    return LocalDataLayer(SAMPLE)


def test_every_researcher_query_matches_sample_mode(local: LocalDataLayer) -> None:
    sample, live = _researcher(local), _researcher(_live(local))
    supplier = local.run_sql("SELECT supplier_raw FROM {spend} WHERE council = 'Woking' LIMIT 1")[0]["supplier_raw"]
    calls = [
        ("supplier_spend", (COUNCILS,), {}),
        ("council_windows", (COUNCILS,), {}),
        ("supplier_rows", ("Woking", supplier), {"limit": 1000}),
        ("contracts_near", (COUNCILS, "2027-04-01", 180), {}),
        ("contracts_without_end_date", (COUNCILS,), {}),
        ("contracts_summary", (COUNCILS,), {}),
        ("policy_clauses", (["Woking", "Guildford"],), {}),
    ]
    for name, args, kwargs in calls:
        want = getattr(sample, name)(*args, **kwargs)
        got = getattr(live, name)(*args, **kwargs)
        assert want, f"{name}: sample mode returned nothing to compare"
        assert _canon(got) == _canon(want), f"{name}: live rows differ from sample mode"


def test_partial_answer_is_refused(local: LocalDataLayer) -> None:
    live = _live(local, cap=100)  # a Zetaris that silently stops at 100 rows
    with pytest.raises(DataLayerError) as e:
        live.run_sql("SELECT provenance_id FROM {spend}", limit=5000)
    assert e.value.type_ == "TruncatedResult"
