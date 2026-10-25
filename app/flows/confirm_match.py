"""Flow: a human confirms (or splits) a supplier pair.

Router -> Researcher (verify both names exist, find their councils) ->
ApprovalGate (record the human decision) -> Memory (store it in H-MEM, long-term).
The next supplier_overlap run recalls it: that is the memory engine changing a later answer.
"""

from __future__ import annotations

from typing import Any

from app.agents.approval import ApprovalGateAgent
from app.agents.base import RunContext
from app.agents.memory import MemoryAgent
from app.agents.researcher import ResearcherAgent
from app.matching import normalise


class FlowError(Exception):
    pass


def _find_council(researcher: ResearcherAgent, name: str, hint: str | None, spend: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (council, exact supplier_raw as stored) for a user-typed name."""
    n = normalise(name)
    hits = [r for r in spend if normalise(r["supplier_raw"]) == n and (not hint or r["council"] == hint)]
    if not hits:
        hits = [r for r in spend if name.strip().upper() in r["supplier_raw"].upper() and (not hint or r["council"] == hint)]
    if not hits:
        raise FlowError(f"'{name}' is not a supplier name in {hint or 'any council'}'s published spend; use the exact name from the overlap table")
    r = hits[0]
    return r["council"], r["supplier_raw"]


def run(ctx: RunContext, sources: dict[str, Any]) -> dict[str, Any]:
    p = ctx.params
    if not p.get("a_name") or not p.get("b_name"):
        raise FlowError("Say which two supplier records you are confirming, in quotes, e.g. Confirm that 'A' (Woking) is the same supplier as 'B' (Guildford)")
    researcher = ResearcherAgent(ctx)
    gate = ApprovalGateAgent(ctx)
    memory = MemoryAgent(ctx)

    spend = researcher.supplier_spend(["Woking", "Guildford", "Waverley"])
    a_council, a_name = _find_council(researcher, p["a_name"], p.get("a_council"), spend)
    b_council, b_name = _find_council(researcher, p["b_name"], p.get("b_council"), spend)
    if a_council == b_council:
        raise FlowError(f"both names are in {a_council}'s data; a cross-council match needs two different councils")
    verdict = "same" if p.get("decision", "same") == "same" else "split"

    human = gate.confirm_match(a_council, a_name, b_council, b_name, verdict)
    stored = memory.remember_decision(a_council, a_name, b_council, b_name, verdict, actor=human["actor"])
    a_rows = researcher.supplier_rows(a_council, a_name, limit=3)
    b_rows = researcher.supplier_rows(b_council, b_name, limit=3)

    summary = (
        f"Recorded: '{a_name}' ({a_council}) and '{b_name}' ({b_council}) are "
        f"{'the same organisation' if verdict == 'same' else 'different organisations'}. "
        f"Stored in H-MEM as {stored['memory_id']} (long_term, confidence 1.0, source human:approval-gate). "
        f"Every later supplier-overlap answer will resolve this pair using {stored['memory_id']}."
    )
    return {
        "summary": summary,
        "recommendations": [
            "Re-run the supplier overlap question to see the pair resolved from memory.",
            f"If this was wrong, send the opposite decision for the same pair; the new decision supersedes {stored['memory_id']} (the old one is kept and penalised, never deleted).",
        ],
        "artifacts": [
            {"type": "decision", "title": "Human decision", "decision": stored, "verdict": verdict},
            {"type": "evidence", "title": "Published rows behind each name", "a": {"council": a_council, "name": a_name, "rows": a_rows}, "b": {"council": b_council, "name": b_name, "rows": b_rows}},
            {"type": "memory", "title": "H-MEM ledger entries for this decision", "ledger_tail": memory.ledger_tail(4), "memory_dir": str(ctx.settings.memory_dir)},
        ],
    }
