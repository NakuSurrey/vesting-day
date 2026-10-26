"""The Zetaris Unified Semantic Layer: its SQL, the runner that builds it, and reading through it.

scripts/zetaris/usl.sql builds the USL "west_surrey" over the three council sources, and
scripts/zetaris/build_usl.py sends it to Zetaris step by step. These tests check, with no network:
- the steps are in an order Zetaris can run, and the multi-table COMPILE is sent as one request;
- the USL tables carry every column of the council tables, activated over all three sources;
- the USL queries give the same answer as the agent's own contract-cliff run;
- with ZETARIS_USL set, every Researcher query read through the USL matches SAMPLE_MODE;
- the runner records what came back, stops when a build step fails, and never writes the key.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.datalayer import LocalDataLayer, ZetarisDataLayer
from app.agents.researcher import ResearcherAgent

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
COUNCILS = ["Woking", "Guildford", "Waverley"]

_spec = importlib.util.spec_from_file_location("build_usl", ROOT / "scripts" / "zetaris" / "build_usl.py")
build_usl = importlib.util.module_from_spec(_spec)
sys.modules["build_usl"] = build_usl
_spec.loader.exec_module(build_usl)
USL = build_usl.USL


@pytest.fixture(scope="module")
def steps():
    return build_usl.parse_steps(build_usl.SQL_FILE.read_text(encoding="utf-8"))


def _index(steps, name):
    return next(i for i, s in enumerate(steps) if s.name == name)


def test_steps_run_in_an_order_zetaris_accepts(steps) -> None:
    kinds = [s.kind for s in steps]
    assert kinds.index("build") > max(i for i, k in enumerate(kinds) if k == "explore")
    assert _index(steps, "parent_namespace") < _index(steps, "namespace") < _index(steps, "compile") < _index(steps, "activate_council")
    assert steps[_index(steps, "parent_namespace")].sql == "CREATE NAMESPACE IF NOT EXISTS lightning.metastore"
    assert max(i for i, s in enumerate(steps) if s.name.startswith("activate_")) < min(i for i, k in enumerate(kinds) if k == "query")
    assert _index(steps, "register_contract_has_end_date") < _index(steps, "run_contract_has_end_date")
    assert _index(steps, "register_payment_is_positive") < _index(steps, "run_payment_is_positive")
    # at least 2-3 exploratory queries per source, at least 2 USL queries, at least one rule run
    for council in COUNCILS:
        assert sum(1 for s in steps if s.kind == "explore" and s.name.startswith(council.lower())) >= 3
    assert sum(1 for k in kinds if k == "query") >= 2
    assert any(s.kind == "dq" and s.sql.startswith("RUN DQ") for s in steps)
    # comment lines are not sent, and the four table definitions travel in one request
    assert not any(line.lstrip().startswith("--") for s in steps for line in s.sql.splitlines())
    compile_sql = steps[_index(steps, "compile")].sql
    assert compile_sql.startswith(f"COMPILE USL IF NOT EXISTS west_surrey DEPLOY NAMESPACE lightning.metastore.vesting_day DDL")
    assert compile_sql.count("CREATE TABLE") == 4


def _schema_columns(sql: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for table, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\)", sql, flags=re.S):
        cols = [line.strip().split()[0] for line in body.splitlines() if line.strip() and not line.strip().upper().startswith("PRIMARY KEY")]
        out[table] = cols
    return out


def test_usl_tables_mirror_the_council_tables(steps) -> None:
    council_tables = _schema_columns((ROOT / "scripts" / "zetaris" / "schema.sql").read_text(encoding="utf-8"))
    usl_tables = _schema_columns(steps[_index(steps, "compile")].sql)
    assert set(usl_tables) == {"council", "spend", "contracts", "policy_clause"}
    for table, cols in council_tables.items():
        missing = set(cols) - set(usl_tables[table])
        assert not missing, f"USL table {table} lacks {missing}, so the Researcher could not read it through the USL"
        activation = steps[_index(steps, f"activate_{table}")].sql
        for src in ("woking_pg", "guildford_pg", "waverley_pg"):
            assert f"FROM {src}.{table}" in activation
        for col in usl_tables[table]:
            assert activation.count(f" AS {col}") == 3, f"{table}.{col} is not bound from all three sources"
    compile_sql = steps[_index(steps, "compile")].sql
    for table in ("spend", "contracts", "policy_clause"):
        body = re.search(rf"CREATE TABLE {table} \((.*?)\n\)", compile_sql, flags=re.S).group(1)
        assert "council varchar(20) NOT NULL FOREIGN KEY REFERENCES council(council)" in re.sub(r"\s+", " ", body)


def test_usl_queries_agree_with_the_agents_own_run(steps) -> None:
    conn = build_usl.sample_connection(SAMPLE)
    payments = build_usl.sample_answer(conn, steps[_index(steps, "usl_payments_per_council")].sql)
    assert {r["council"] for r in payments} == set(COUNCILS)
    assert all(r["zetaris_source"] == f"{r['council'].lower()}_pg" for r in payments)

    cliff = {r["council"]: r for r in build_usl.sample_answer(conn, steps[_index(steps, "usl_contract_cliff")].sql)}
    agent = json.loads((ROOT / "output_examples" / "04_contract_cliff.json").read_text(encoding="utf-8"))
    stats = next(a for a in agent["output"]["artifacts"] if a.get("type") == "run_stats")
    for council, v in stats["per_council"].items():
        assert cliff[council]["hard_cliff_contracts"] == v["contracts"]
        assert round(cliff[council]["stated_value_gbp"], 2) == round(v["value_gbp"], 2)
    assert round(sum(r["stated_value_gbp"] for r in cliff.values()), 2) == round(stats["total_hard_cliff_gbp"], 2)


def _usl_fake_zetaris(local: LocalDataLayer, seen: list[str] | None = None):
    """A Zetaris whose USL tables are the sample tables, answering in the real REST shape (all text)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("ATTACH DATABASE ':memory:' AS usl")
    for table in ("spend", "contracts", "policy_clause"):
        info = local.conn.execute(f"PRAGMA table_info({table})").fetchall()
        extra = ["clause_id TEXT"] if table == "policy_clause" else []
        conn.execute(f"CREATE TABLE usl.{table} ({', '.join(extra + [f'{c[1]} {c[2]}' for c in info])})")
        cols = [c[1] for c in info]
        rows = local.conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
        if table == "policy_clause":
            rows = [(f"{r[cols.index('policy_family')]}|{r[cols.index('council')]}|{r[cols.index('clause_key')]}", *r) for r in rows]
            cols = ["clause_id"] + cols
        conn.executemany(f"INSERT INTO usl.{table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [tuple(r) for r in rows])

    def handler(request: httpx.Request) -> httpx.Response:
        sql = json.loads(request.content)["sql"]
        if seen is not None:
            seen.append(sql)
        assert USL in sql and "UNION ALL" not in sql, "with ZETARIS_USL set the agent must read through the USL"
        cur = conn.execute(sql.replace(USL + ".", "usl."))
        data = [[None if v is None else str(v) for v in r] for r in cur.fetchall()]
        return httpx.Response(200, json={"headers": [d[0] for d in cur.description], "data": data, "total": len(data)})

    return handler


def test_the_switch_reads_through_the_usl_only_when_set() -> None:
    plain = ZetarisDataLayer("http://zetaris.test/api/v1.0", "1", "test-key")
    assert "UNION ALL" in plain.render("SELECT 1 FROM {contracts}") and "semantic" not in plain.name
    usl = ZetarisDataLayer("http://zetaris.test/api/v1.0", "1", "test-key", usl=USL)
    assert usl.render("SELECT 1 FROM {contracts}") == f"SELECT 1 FROM {USL}.contracts AS contracts"
    assert "unified semantic layer" in usl.name
    with pytest.raises(ValueError):
        ZetarisDataLayer("http://zetaris.test/api/v1.0", "1", "test-key", usl="x; DROP TABLE spend")


def test_every_researcher_query_through_the_usl_matches_sample_mode() -> None:
    local = LocalDataLayer(SAMPLE)
    seen: list[str] = []
    layer = ZetarisDataLayer("http://zetaris.test/api/v1.0", "1", "test-key", usl=USL)
    layer._client = httpx.Client(transport=httpx.MockTransport(_usl_fake_zetaris(local, seen)))
    ctx = lambda d: SimpleNamespace(data=d, agents_used={}, tracer=SimpleNamespace(log=lambda **kw: None))
    sample, live = ResearcherAgent(ctx(local)), ResearcherAgent(ctx(layer))
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
    canon = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)
    for name, args, kwargs in calls:
        want = getattr(sample, name)(*args, **kwargs)
        got = getattr(live, name)(*args, **kwargs)
        assert want and canon(got) == canon(want), f"{name}: rows read through the USL differ from sample mode"
    assert len(seen) == len(calls)


def _runner_fake(steps, fail_on: str | None = None, fail_text: str = "compile error"):
    conn = build_usl.sample_connection(SAMPLE)
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append({"headers": dict(request.headers), "body": body})
        sql = body["sql"]
        if fail_on and sql == next(s.sql for s in steps if s.name == fail_on):
            return httpx.Response(400, text=fail_text)
        if sql.startswith("SELECT") and USL in sql:
            rows = build_usl.sample_answer(conn, sql)
            cols = list(rows[0].keys()) if rows else ["n"]
            return httpx.Response(200, json={"headers": cols, "data": [[str(r[c]) for c in cols] for r in rows], "total": len(rows)})
        return httpx.Response(200, json={"headers": ["result"], "data": [["registered"]], "total": 1})

    return handler, sent, conn


def test_runner_sends_each_block_whole_and_writes_evidence_without_the_key(steps, tmp_path: Path) -> None:
    handler, sent, conn = _runner_fake(steps)
    z = build_usl.Zetaris("http://zetaris.test/api/v1.0", "1", "secret-test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    results = build_usl.run_steps(steps, z, log=lambda s: None, sample=conn)
    assert len(sent) == len(steps) and all(r["status"] == "success" for r in results)
    assert [x["body"]["sql"] for x in sent] == [s.sql for s in steps]
    assert all(x["headers"]["authorization"] == "Bearer secret-test-key" and x["headers"]["x-org-id"] == "1" for x in sent)
    assert all(r["matches_sample_mode"] for r in results if r["kind"] == "query")

    md, jsonl = tmp_path / "EVIDENCE.md", tmp_path / "build.jsonl"
    build_usl.write_evidence(results, "2026-10-26T22:00:00Z", jsonl=jsonl, md=md)
    text = md.read_text(encoding="utf-8")
    assert f"{len(steps)} of {len(steps)} steps succeeded" in text and "COMPILE USL" in text
    assert "secret-test-key" not in text and "secret-test-key" not in jsonl.read_text(encoding="utf-8")
    assert len(jsonl.read_text(encoding="utf-8").splitlines()) == len(steps)


def test_runner_stops_when_a_build_step_fails_but_not_on_a_rerun(steps) -> None:
    handler, sent, conn = _runner_fake(steps, fail_on="compile")
    z = build_usl.Zetaris("http://zetaris.test/api/v1.0", "1", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    results = build_usl.run_steps(steps, z, log=lambda s: None, sample=conn)
    assert results[-1]["name"] == "compile" and results[-1]["status"] == "error"
    assert not any(x["body"]["sql"].startswith("ACTIVATE") for x in sent)

    handler, sent, conn = _runner_fake(steps, fail_on="compile", fail_text="USL west_surrey already exists")
    z = build_usl.Zetaris("http://zetaris.test/api/v1.0", "1", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    results = build_usl.run_steps(steps, z, log=lambda s: None, sample=conn)
    assert len(results) == len(steps)


def test_a_missing_parent_namespace_stops_the_run(steps) -> None:
    # the first live run: "parent namespace : metastore is not existing" contains "exist" but is a real failure
    msg = '{"msg":"NamespaceException: parent namespace : metastore is not existing"}'
    handler, sent, conn = _runner_fake(steps, fail_on="namespace", fail_text=msg)
    z = build_usl.Zetaris("http://zetaris.test/api/v1.0", "1", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    results = build_usl.run_steps(steps, z, log=lambda s: None, sample=conn)
    assert results[-1]["name"] == "namespace" and results[-1]["status"] == "error"
    assert not any(x["body"]["sql"].startswith("COMPILE") for x in sent)


def test_only_an_object_that_already_exists_counts_as_a_rerun() -> None:
    for msg in ("USL west_surrey already exists", "namespace : vesting_day is existing"):
        assert build_usl.already_exists(msg), msg
    for msg in ("parent namespace : metastore is not existing", "namespace not found : vesting_day",
                "table does not exist", "Schema mismatch for table 'x.spend'"):
        assert not build_usl.already_exists(msg), msg


def _select_items(select_sql: str) -> list[str]:
    """The comma-separated items between SELECT and FROM, splitting only at top level."""
    body = select_sql.split("SELECT", 1)[1].rsplit("\nFROM", 1)[0].rsplit(" FROM ", 1)[0]
    items, depth, quote, cur = [], 0, False, ""
    for ch in body:
        if ch == "'":
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not quote:
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return items + [cur.strip()]


def test_every_not_null_column_is_fed_a_value_that_cannot_be_null(steps) -> None:
    # Zetaris refuses an activation whose column may be null where the DDL says NOT NULL; a CAST
    # around a COALESCE counts as nullable (the first live run failed on amount_gbp this way).
    compile_sql = steps[_index(steps, "compile")].sql
    for table, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\)", compile_sql, flags=re.S):
        not_null = {line.split()[0] for line in body.splitlines() if "NOT NULL" in line}
        parts = steps[_index(steps, f"activate_{table}")].sql.split(" AS\n", 1)[1].split("\nUNION ALL\n")
        assert len(parts) == 3
        for part in parts:
            for item in _select_items(part):
                expr, alias = item.rsplit(" AS ", 1)
                if alias.strip() in not_null:
                    expr = expr.strip()
                    assert expr.startswith("COALESCE(") or re.fullmatch(r"'[^']*'", expr), f"{table}.{alias}: {expr}"
