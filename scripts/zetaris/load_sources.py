"""Load data/sample/*.csv into the three per-council Postgres schemas.

Connection string comes from the VD_PG_DSN environment variable, e.g.
postgresql://vd:...@localhost:5432/vestingday (never written into the repo).

Run on the Zetaris host, from the repo root:
  uv run --group prep python scripts/zetaris/load_sources.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    sys.exit("psycopg is needed: uv sync --group prep")

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"
COUNCILS = ("Woking", "Guildford", "Waverley")


def _none(v: str) -> str | None:
    return None if v == "" else v


def load_table(cur: psycopg.Cursor, schema: str, table: str, rows: list[dict], cols: list[str]) -> int:
    cur.execute(f"TRUNCATE {schema}.{table}")
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {schema}.{table} ({', '.join(cols)}) VALUES ({placeholders})"
    cur.executemany(sql, [[_none(r[c]) for c in cols] for r in rows])
    return len(rows)


def main() -> None:
    dsn = os.environ.get("VD_PG_DSN")
    if not dsn:
        sys.exit("set VD_PG_DSN to the Postgres connection string")
    with open(SAMPLE / "spend.csv", newline="", encoding="utf-8") as fh:
        spend = list(csv.DictReader(fh))
    with open(SAMPLE / "contracts.csv", newline="", encoding="utf-8") as fh:
        contracts = list(csv.DictReader(fh))
    with open(SAMPLE / "policy_clauses.csv", newline="", encoding="utf-8") as fh:
        clauses = list(csv.DictReader(fh))
    spend_cols = list(spend[0].keys())
    contract_cols = list(contracts[0].keys())
    clause_cols = list(clauses[0].keys())

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for council in COUNCILS:
            schema = council.lower()
            n1 = load_table(cur, schema, "spend", [r for r in spend if r["council"] == council], spend_cols)
            n2 = load_table(cur, schema, "contracts", [r for r in contracts if r["council"] == council], contract_cols)
            n3 = load_table(cur, schema, "policy_clause", [r for r in clauses if r["council"] == council], clause_cols)
            print(f"{schema}: spend {n1}, contracts {n2}, policy_clause {n3}")
        conn.commit()


if __name__ == "__main__":
    main()
