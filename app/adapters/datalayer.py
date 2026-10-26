"""The data layer the Researcher agent talks to.

Live mode:   ZetarisDataLayer  - Zetaris REST (query-in-place over the three councils)
Sample mode: LocalDataLayer    - the same SQL over an in-memory SQLite loaded from data/sample

Both expose run_sql(sql) -> list[dict]. SQL is written in a plain subset with
table placeholders {spend}, {contracts}, {policy_clause} that each layer maps
to its own table names, so the agent code path is identical in both modes.
"""

from __future__ import annotations

import csv
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx


class DataLayerError(Exception):
    def __init__(self, message: str, recoverable: bool = True, type_: str = "UpstreamError") -> None:
        super().__init__(message)
        self.recoverable = recoverable
        self.type_ = type_


class DataLayer:
    name = "abstract"
    tables: dict[str, str] = {}

    def run_sql(self, sql: str, limit: int = 1000) -> list[dict[str, Any]]:
        raise NotImplementedError

    def render(self, sql: str) -> str:
        return sql.format(**self.tables)

    def describe(self) -> dict[str, Any]:
        return {"layer": self.name, "tables": dict(self.tables)}


# --- SAMPLE_MODE: SQLite over the cached council files -------------------------

class LocalDataLayer(DataLayer):
    name = "local-sqlite (SAMPLE_MODE cache of the published council files)"
    tables = {"spend": "spend", "contracts": "contracts", "policy_clause": "policy_clause"}

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._load_csv("spend", data_dir / "spend.csv", numeric=("amount_gbp",))
        self._load_csv("contracts", data_dir / "contracts.csv", numeric=("annual_value_gbp", "total_value_gbp"))
        self._load_csv("policy_clause", data_dir / "policy_clauses.csv", numeric=("value_num",), optional=True)

    def _load_csv(self, table: str, path: Path, numeric: tuple[str, ...] = (), optional: bool = False) -> None:
        if not path.exists():
            if optional:
                self.conn.execute(f"CREATE TABLE {table} (policy_family TEXT, council TEXT, clause_key TEXT, value_text TEXT, value_num REAL, unit TEXT, source_pdf TEXT, page INTEGER, quote TEXT)")
                return
            raise DataLayerError(f"sample data missing: {path}", recoverable=False, type_="SampleDataMissing")
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            cols = reader.fieldnames or []
            defs = ", ".join(f"{c} {'REAL' if c in numeric else 'TEXT'}" for c in cols)
            self.conn.execute(f"CREATE TABLE {table} ({defs})")
            rows = []
            for r in reader:
                rows.append([(float(r[c]) if c in numeric and r[c] not in ("", None) else (None if r[c] == "" else r[c])) for c in cols])
            self.conn.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in cols)})", rows)
        self.conn.commit()

    def run_sql(self, sql: str, limit: int = 1000) -> list[dict[str, Any]]:
        q = self.render(sql)
        try:
            cur = self.conn.execute(q)
        except sqlite3.Error as e:
            raise DataLayerError(f"local SQL failed: {e}", recoverable=False, type_="QueryError") from e
        out = []
        for i, row in enumerate(cur):
            if i >= limit:
                break
            out.append(dict(row))
        return out


# --- LIVE: Zetaris REST ---------------------------------------------------------

class ZetarisDataLayer(DataLayer):
    """Speaks the Zetaris REST contract from the Participant Setup Guide:
    POST {REST_URL}/sql-editor/sqls/run, Bearer key, X-Org-ID, fresh X-Request-ID,
    body {queryId, sql, source: "SqlEditor", limit}; rows come back in .data."""

    name = "zetaris (federated query-in-place over woking_pg, guildford_pg, waverley_pg)"

    # The three councils are three registered Zetaris datasources (scripts/zetaris/register_sources.sql).
    # Every {spend} / {contracts} / {policy_clause} placeholder becomes a federated UNION across them,
    # so one SQL statement from the Researcher is answered by Zetaris querying all three sources in place.
    SOURCES = ("woking_pg", "guildford_pg", "waverley_pg")

    def __init__(self, rest_url: str, org_id: str, api_key: str, sources: tuple[str, ...] = SOURCES, timeout: float = 60.0) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.org_id = org_id
        self.api_key = api_key
        self.timeout = timeout
        self.sources = sources
        self.tables = {t: self._federated(t) for t in ("spend", "contracts", "policy_clause")}
        self._client = httpx.Client(timeout=timeout)

    def _federated(self, table: str) -> str:
        return "(" + " UNION ALL ".join(f"SELECT * FROM {src}.{table}" for src in self.sources) + f") AS {table}"

    def run_sql(self, sql: str, limit: int = 1000) -> list[dict[str, Any]]:
        q = self.render(sql)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Org-ID": str(self.org_id),
            "X-Request-ID": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        body = {"queryId": str(uuid.uuid4()), "sql": q, "source": "SqlEditor", "limit": limit}
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = self._client.post(f"{self.rest_url}/sql-editor/sqls/run", headers=headers, json=body)
                if r.status_code >= 500:
                    last_err = DataLayerError(f"Zetaris returned {r.status_code}", True, "UpstreamError")
                    continue
                if r.status_code >= 400:
                    raise DataLayerError(f"Zetaris rejected the query ({r.status_code}): {r.text[:300]}", False, "QueryError")
                payload = r.json()
                rows = _rows_from_payload(payload)
                total = payload.get("total") if isinstance(payload, dict) else None
                if isinstance(total, int) and total > len(rows) and len(rows) < limit:
                    # Zetaris cut the result short of what we asked for - never answer on part of the data.
                    raise DataLayerError(
                        f"Zetaris returned {len(rows)} of {total} rows (asked for up to {limit}); refusing to answer on partial data",
                        recoverable=False,
                        type_="TruncatedResult",
                    )
                return rows
            except httpx.HTTPError as e:
                last_err = e
        raise DataLayerError(
            f"Zetaris did not respond after 3 retries ({last_err}); set SAMPLE_MODE=true to run on cached data.",
            recoverable=True,
            type_="UpstreamTimeout",
        )


# Zetaris's REST API sends every value as text. These are the columns the agents use as
# numbers or dates; converting them here gives live rows the same types as the SAMPLE_MODE
# SQLite cache. Everything else stays text, so codes like "01234567" keep their leading zero.
_INT_COLUMNS = {"n_payments", "rows_published", "distinct_suppliers", "contracts", "no_end_date"}
_FLOAT_COLUMNS = {"amount_gbp", "total_gbp", "annual_value_gbp", "total_value_gbp", "value_num"}
_DATE_COLUMNS = {
    "payment_date", "invoice_date", "start_date", "end_date", "max_extension_end",
    "first_payment", "last_payment", "payment_from", "payment_to", "earliest_end", "latest_end",
}


def _typed(col: str, v: Any) -> Any:
    if v is None or not isinstance(v, str):
        return v
    if v == "":
        return None
    try:
        if col in _INT_COLUMNS:
            return int(float(v))
        if col in _FLOAT_COLUMNS:
            return float(v)
    except ValueError:
        return v
    if col in _DATE_COLUMNS and len(v) > 10 and v[4] == "-" and v[10] in " T":
        return v[:10]  # "2027-04-14 00:00:00" -> "2027-04-14"
    return v


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Turn a Zetaris answer into a list of {column: value} rows.

    The live API answers {"headers": [...], "data": [[...], ...], "total": n}. Older shapes
    are still accepted: a bare list, {"data": [...]} of dicts, or {"columns", "rows"}.
    """
    if isinstance(payload, dict) and "headers" in payload:
        cols = [h.get("name") if isinstance(h, dict) else str(h) for h in payload["headers"]]
        return [{c: _typed(c, v) for c, v in zip(cols, r)} for r in (payload.get("data") or [])]
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(rows, dict) and "columns" in rows and "rows" in rows:
        cols = [c["name"] if isinstance(c, dict) else str(c) for c in rows["columns"]]
        return [{c: _typed(c, v) for c, v in zip(cols, r)} for r in rows["rows"]]
    if isinstance(rows, list):
        return [{k: _typed(k, v) for k, v in r.items()} if isinstance(r, dict) else {"value": r} for r in rows]
    return []
