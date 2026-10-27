"""H-MEM conformance suite - pytest port of the official runner
(github.com/Meterless/Meterless engines/hmem/conformance/runner.ts).

Runs the Python engine against the UNMODIFIED upstream vectors
(third_party/hmem/vectors.json). Each vector becomes one pytest case with the
upstream id, so the scorecard reads the same as the official runner:
13 checks across 7 sections. Assertions are the exact tier: formula
arithmetic, deltas, gates and boundaries the reference fully determines.

Run:  uv run pytest tests/test_hmem_conformance.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.engines.hmem import HMEM

VECTORS = json.loads((Path(__file__).resolve().parents[1] / "third_party" / "hmem" / "vectors.json").read_text())
T0: int = VECTORS["clock"]
DAY = 24 * 60 * 60 * 1000
S = VECTORS["sections"]


def approx(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(a - b) < eps


def _ids(section: str) -> list[str]:
    return [c["id"] for c in S[section]]


# --- record-validation -------------------------------------------------------

@pytest.mark.parametrize("c", S["record-validation"], ids=_ids("record-validation"))
def test_record_validation(c):
    hmem = HMEM(clock=lambda: T0)
    rejected = False
    try:
        hmem.add(content=c["input"]["content"], source=c["input"]["source"])
    except Exception:
        rejected = True
    assert rejected == (c["expect"] == "reject"), f"expected {c['expect']}, got {'reject' if rejected else 'accept'}"


# --- feedback-deltas ---------------------------------------------------------

@pytest.mark.parametrize("c", S["feedback-deltas"], ids=_ids("feedback-deltas"))
def test_feedback_deltas(c):
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=c["start"], source="conformance")
    access_before = m.access_count
    hmem.feedback(m.id, c["kind"])
    after = hmem.store.get(m.id)
    assert approx(after.confidence, c["expectConfidence"]), f"confidence {after.confidence}, expected {c['expectConfidence']}"
    if "expectAccessDelta" in c:
        delta = after.access_count - access_before
        assert delta == c["expectAccessDelta"], f"accessCount delta {delta}, expected {c['expectAccessDelta']}"
    if c.get("expectTag"):
        assert c["expectTag"] in after.tags, f"missing tag {c['expectTag']}"


# --- ranking-order -----------------------------------------------------------

@pytest.mark.parametrize("c", S["ranking-order"], ids=_ids("ranking-order"))
def test_ranking_order(c):
    hmem = HMEM(clock=lambda: T0)
    by_key = {}
    for r in c["records"]:
        by_key[r["key"]] = hmem.add(content=r["content"], confidence=r["confidence"], layer=r["layer"], source="conformance")
    for r in c["records"]:
        if r.get("supersededByKey"):
            by_key[r["key"]].superseded_by = by_key[r["supersededByKey"]].id
    result = hmem.query(c["query"], threshold=0, top_n=10)
    order = [rm.memory.id for rm in result.memories]
    expected = [by_key[k].id for k in c["expectOrder"]]
    for i in range(len(expected) - 1):
        assert order.index(expected[i]) < order.index(expected[i + 1]), (
            f"expected {c['expectOrder'][i]} before {c['expectOrder'][i + 1]}, got {order}"
        )


# --- sleep-guardrails --------------------------------------------------------

@pytest.mark.parametrize("c", S["sleep-guardrails"], ids=_ids("sleep-guardrails"))
def test_sleep_guardrails(c):
    now = {"t": T0}
    hmem = HMEM(clock=lambda: now["t"])
    by_key = {}
    for r in c["records"]:
        by_key[r["key"]] = hmem.add(content=r["content"], source=r["source"], derived_from=r.get("derivedFrom"))
    now["t"] = T0 + c["ageDays"] * DAY
    before = sorted(m.id for m in hmem.store.all())
    preview = hmem.sleep.preview()
    assert sorted(m.id for m in hmem.store.all()) == before, "preview mutated the store"
    for k in c["expectArchived"]:
        assert by_key[k].id in preview.to_archive, f"{k} should be archivable"
    for k in c["expectProtected"]:
        assert by_key[k].id not in preview.to_archive, f"{k} is guardrail-protected and must not archive"
    report = hmem.sleep.execute(preview)
    for k in c["expectProtected"]:
        assert hmem.store.get(by_key[k].id) is not None, f"{k} was deleted despite guardrails"
    assert isinstance(report.backup_id, str) and len(report.backup_id) > 0, "execute must return a backupId"


# --- conflict-gate -----------------------------------------------------------

@pytest.mark.parametrize("c", S["conflict-gate"], ids=_ids("conflict-gate"))
def test_conflict_gate(c):
    hmem = HMEM(clock=lambda: T0)
    a = hmem.add(content=c["a"]["content"], confidence=c["a"]["confidence"], source="conformance")
    b = hmem.add(content=c["b"]["content"], confidence=c["b"]["confidence"], source="conformance")
    found = hmem.conflicts.scan()
    assert len(found) > 0, "opposing always/never pair on similar content must be detected"
    outcome = hmem.conflicts.auto_resolve(found[0])
    assert outcome in ("resolved", "queued"), f"outcome must be resolved or queued, got {outcome}"
    if outcome == "resolved":
        loser = next((m for m in (hmem.store.get(a.id), hmem.store.get(b.id)) if m and m.superseded_by), None)
        assert loser is not None, "resolved conflicts must mark the loser supersededBy"
    assert hmem.store.get(a.id) and hmem.store.get(b.id), "conflict resolution must never delete records"


# --- ledger-audit ------------------------------------------------------------

@pytest.mark.parametrize("c", S["ledger-audit"], ids=_ids("ledger-audit"))
def test_ledger_audit(c):
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="audited record", confidence=c["start"], source="conformance")
    hmem.feedback(m.id, c["kind"])
    history = hmem.ledger.history(m.id)
    actions = [h.action for h in history]
    assert actions == c["expectActions"], f"actions {actions}, expected {c['expectActions']}"
    fb = history[-1]
    assert approx((fb.previous_state or {}).get("confidence"), c["expectPrev"]), (
        f"previousState.confidence {(fb.previous_state or {}).get('confidence')}, expected {c['expectPrev']}"
    )
    assert approx((fb.new_state or {}).get("confidence"), c["expectNew"]), (
        f"newState.confidence {(fb.new_state or {}).get('confidence')}, expected {c['expectNew']}"
    )


# --- dream-boundary ----------------------------------------------------------

@pytest.mark.parametrize("c", S["dream-boundary"], ids=_ids("dream-boundary"))
def test_dream_boundary(c):
    hmem = HMEM(clock=lambda: T0)
    for r in c["records"]:
        hmem.add(content=r["content"], type=r["type"], source="conformance")
    count_before = len(hmem.store.all())
    proposals = hmem.dreaming.dream()
    assert len(proposals) > 0, "two related preferences must produce at least one proposal"
    assert len(hmem.store.all()) == count_before, "dreaming must not materialize anything before approval"
    created = hmem.dreaming.approve(proposals[0].id)
    if created is not None:
        assert created.layer == "long_term", "approved proposals materialize as long_term"
        assert len(created.derived_from or []) > 0, "approved proposals carry derivedFrom lineage"


def test_vector_count_is_thirteen():
    # Guards against silently running fewer checks than the official suite.
    total = sum(len(v) for v in S.values())
    assert total == 13, f"expected 13 upstream vectors, found {total}"
