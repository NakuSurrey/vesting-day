"""Action lists as spreadsheets: every table an answer shows is also written in full as CSV.

The JSON response keeps short preview rows (the page shows 12). The full list - all 173
contracts, every shared supplier, the whole queue awaiting a human decision - is written next
to the run's trace as logs/exports/<run_id>/<slug>.csv, and the table artifact gains
"export": {"file", "url", "rows"} so the web page can offer "Download all rows (CSV)".
A flow passes the full list as "_all_rows"; it is removed from the response here.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterator

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
KEEP_WEB_EXPORTS = 200          # a hosted demo keeps the newest web runs' folders and traces only


def _tables(artifacts: list[dict[str, Any]], prefix: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    for a in artifacts:
        if a.get("type") == "table":
            yield prefix, a
        elif a.get("type") == "step_results":
            for s in a.get("steps", []):
                yield from _tables(s.get("artifacts", []), prefix=f"{s.get('check', 'step')}-".replace("_", "-"))


def slug(title: str, prefix: str, used: set[str]) -> str:
    words = re.findall(r"[a-z0-9]+", (title or "table").lower())[:6]
    base = (prefix + "-".join(words))[:60].strip("-") or "table"
    name, n = base, 2
    while name in used:
        name, n = f"{base}-{n}", n + 1
    used.add(name)
    return name


def _cell(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return "" if v is None else v


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:    # utf-8-sig: opens cleanly in Excel
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_cell(r.get(c)) for c in cols])


def export_tables(artifacts: list[dict[str, Any]], logs_dir: Path, run_id: str) -> int:
    """Write every table of this answer as CSV; returns how many files were written."""
    used: set[str] = set()
    written = 0
    for prefix, a in _tables(artifacts):
        rows = a.pop("_all_rows", None)
        if rows is None:
            rows = a.get("rows") or []
        if not rows:
            continue
        name = slug(a.get("title", ""), prefix, used)
        folder = logs_dir / "exports" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        write_csv(folder / f"{name}.csv", rows)
        a["export"] = {"file": f"logs/exports/{run_id}/{name}.csv", "url": f"/export/{run_id}/{name}.csv", "rows": len(rows)}
        written += 1
    if run_id.startswith("web-"):
        _prune(logs_dir)
    return written


def _prune(logs_dir: Path) -> None:
    import shutil
    runs = sorted((logs_dir / "exports").glob("web-*"), key=lambda p: p.stat().st_mtime)
    for p in runs[:-KEEP_WEB_EXPORTS]:
        shutil.rmtree(p, ignore_errors=True)
    traces = sorted(logs_dir.glob("trace-web-*.jsonl"), key=lambda p: p.stat().st_mtime)   # and their traces, so a busy demo cannot fill the disk
    for p in traces[:-KEEP_WEB_EXPORTS]:
        p.unlink(missing_ok=True)


def export_path(logs_dir: Path, run_id: str, name: str) -> Path | None:
    """The file behind GET /export/<run_id>/<name>.csv, or None if the name is not one this app writes."""
    if not NAME.fullmatch(name):
        return None
    p = logs_dir / "exports" / run_id / f"{name}.csv"
    return p if p.is_file() else None
