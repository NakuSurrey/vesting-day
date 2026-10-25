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

    name = "zetaris (federated query-in-place)"

    def __init__(self, rest_url: str, org_id: str, api_key: str, table_prefix: str = "", timeout: float = 60.0) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.org_id = org_id
        self.api_key = api_key
        self.timeout = timeout
        p = table_prefix
        self.tables = {"spend": f"{p}spend", "contracts": f"{p}contracts", "policy_clause": f"{p}policy_clause"}
        self._client = httpx.Client(timeout=timeout)

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
                rows = payload.get("data") if isinstance(payload, dict) else payload
                return _normalise_rows(rows or [])
            except httpx.HTTPError as e:
                last_err = e
        raise DataLayerError(
            f"Zetaris did not respond after 3 retries ({last_err}); set SAMPLE_MODE=true to run on cached data.",
            recoverable=True,
            type_="UpstreamTimeout",
        )


def _normalise_rows(rows: Any) -> list[dict[str, Any]]:
    """Zetaris may return a list of dicts, or {columns:[...], rows:[[...]]}."""
    if isinstance(rows, dict) and "columns" in rows and "rows" in rows:
        cols = [c["name"] if isinstance(c, dict) else str(c) for c in rows["columns"]]
        return [dict(zip(cols, r)) for r in rows["rows"]]
    if isinstance(rows, list):
        return [dict(r) if isinstance(r, dict) else {"value": r} for r in rows]
    return []
