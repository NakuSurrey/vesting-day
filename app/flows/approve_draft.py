"""Flow: a human approves or rejects a held draft. Nothing is sent either way."""

from __future__ import annotations

from typing import Any

from app.agents.approval import ApprovalGateAgent
from app.agents.base import RunContext
from app.agents.memory import MemoryAgent
from app.engines.hmem import Provenance


class FlowError(Exception):
    pass


def run(ctx: RunContext, sources: dict[str, Any]) -> dict[str, Any]:
    did = ctx.params.get("draft_id")
    decision = ctx.params.get("decision", "approve")
    gate = ApprovalGateAgent(ctx)
    memory = MemoryAgent(ctx)
    if not did:
        pending = ctx.approvals.pending()
        raise FlowError("Say which draft, e.g. 'Approve draft draft-1'. Pending: " + (", ".join(d["id"] for d in pending) or "none"))
    try:
        d = gate.decide_draft(did, decision)
    except KeyError as e:
        raise FlowError(str(e)) from e
    rec = ctx.memory.add(
        content=f"Draft {did} ({d['kind']}: {d['title']}) was {d['status']} by a human.",
        source="human:approval-gate", type="factual", layer="long_term", confidence=1.0,
        tags=["decision:draft", f"draft:{did}", f"status:{d['status']}"],
        provenance=Provenance(origin="user_correction", learned_at=ctx.memory.clock(), label="human approval decision"),
    )
    memory.trace("remember", rec.content, f"stored {rec.id}", confidence=1.0, memory_id=rec.id)
    return {
        "summary": f"{did} is now {d['status']}. It has not been sent anywhere - approval records intent; sending is a human step outside this system. Decision stored in H-MEM as {rec.id}.",
        "recommendations": ["Export the approved text from output.artifacts and send it through the council's own channels."],
        "artifacts": [{"type": "draft", "title": d["title"], "draft": d}, {"type": "memory", "ledger_tail": memory.ledger_tail(3)}],
    }
