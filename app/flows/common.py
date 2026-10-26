"""Helpers shared by the flows: money formatting, evidence numbers, badges."""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence


def gbp(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    return f"GBP {v:,.0f}" if abs(v) >= 1000 else f"GBP {v:,.2f}"


def numbers_in(values: Iterable[Any]) -> set[str]:
    """All numeric spellings that may legitimately appear in a draft built from these values."""
    out: set[str] = set()
    for v in values:
        if v is None:
            continue
        s = str(v)
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", s):
            raw = m.group(0).replace(",", "")
            out.add(raw)
            try:
                f = float(raw)
                out.add(f"{f:,.0f}".replace(",", ""))
                out.add(f"{f:,.2f}".replace(",", ""))
                out.add(f"{f:.0f}")
                out.add(f"{f:.1f}")
            except ValueError:
                pass
    return out


def checked_draft(writer: Any, critic: Any, kind: str, instruction: str, evidence: list[str], template: str,
                  allowed: set[str], claims: Sequence[tuple[str, str]] = (),
                  sections: Sequence[tuple[str, set[str]]] = ()) -> tuple[dict[str, Any], int]:
    """Writer -> Critic, with one retry that carries the Critic's reasons, then the template.

    Returns (draft, bounces). A draft only leaves this function if the Critic accepted it,
    or it is the evidence-only template badged "template-fallback" - never a rejected draft.
    """
    draft = writer.draft(kind, instruction, evidence, template)
    verdict = critic.review_draft(draft["text"], allowed, claims, sections)
    if verdict.accepted:
        return draft, 0
    draft = writer.draft(kind, instruction, evidence, template, retry=1, reasons=verdict.reasons)
    second = critic.review_draft(draft["text"], allowed, claims, sections)
    if second.accepted:
        return draft, 1
    return writer.fallback(kind, template, second.reasons), 2


def window_badges(window_rows: list[dict[str, Any]], sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-council period badge: what window, on what basis, from which files."""
    badges = []
    meta = sources.get("councils", {})
    for r in window_rows:
        c = r["council"]
        m = meta.get(c, {})
        badges.append({
            "council": c,
            "window": m.get("window_label"),
            "basis": m.get("basis"),
            "cadence": m.get("cadence"),
            "format": m.get("format"),
            "rows_published": r.get("rows_published"),
            "total_gbp": r.get("total_gbp"),
            "payment_from": r.get("payment_from"),
            "payment_to": r.get("payment_to"),
            "period_from": r.get("period_from"),
            "period_to": r.get("period_to"),
            "distinct_suppliers": r.get("distinct_suppliers"),
        })
    return badges


def badge_line(b: dict[str, Any]) -> str:
    span = f"{b['payment_from']} to {b['payment_to']}" if b.get("payment_from") else f"periods {b.get('period_from')} to {b.get('period_to')}"
    return f"{b['council']} {b['window']} - {b['cadence']}, by {b['basis']}: {b['rows_published']} rows, {gbp(b['total_gbp'])}, {span}"
