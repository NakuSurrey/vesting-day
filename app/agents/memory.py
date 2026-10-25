"""MemoryAgent: the H-MEM code path. Recalls earlier human decisions and writes new ones.

A confirmed supplier match is a long-term, high-confidence, human-sourced
memory. When the overlap flow runs again, this agent recalls it and the
Resolver resolves the pair "using decision mem-N" - the memory engine visibly
changes a later answer. Every write and read lands in the H-MEM trust ledger
(data/memory/ledger.jsonl) as well as the run trace.
"""

from __future__ import annotations

from typing import Any, Optional

from app.agents.base import Agent
from app.engines.hmem import Provenance
from app.matching import Candidate, normalise, pair_key


class MemoryAgent(Agent):
    name = "Memory"
    role = "Meterless H-MEM: recalls earlier human decisions (supplier matches, approvals) and stores new ones with provenance"

    # --- recall ------------------------------------------------------------

    def recall_decisions(self, candidates: list[Candidate]) -> dict[str, dict[str, Any]]:
        """Return {pair_key: decision} for candidates that a human already decided."""
        decisions: dict[str, dict[str, Any]] = {}
        all_decisions = [m for m in self.ctx.memory.store.all() if "decision:supplier-match" in m.tags]
        if not all_decisions:
            self.trace("recall", f"{len(candidates)} candidate pairs", "no supplier-match decisions in memory yet", target_agent="Resolver", confidence=1.0)
            return decisions
        by_key = {}
        for m in all_decisions:
            key = next((t.split("pair:", 1)[1] for t in m.tags if t.startswith("pair:")), None)
            if key:
                by_key[key] = m
        hits = 0
        for c in candidates:
            m = by_key.get(c.key)
            if m is None:
                continue
            # retrieval through the engine, so the read is ranked and ledgered
            res = self.ctx.memory.query(f"supplier match decision {c.a_name} {c.b_name}", top_n=3, threshold=0.0)
            relevance = res.trace.scores.get(m.id)
            verdict = next((t.split("verdict:", 1)[1] for t in m.tags if t.startswith("verdict:")), "same")
            decisions[c.key] = {"memory_id": m.id, "verdict": verdict, "content": m.content,
                                "confidence": m.confidence, "relevance": relevance, "decided_at": m.provenance.learned_at}
            hits += 1
        self.trace("recall", f"{len(candidates)} candidate pairs against {len(all_decisions)} stored decisions",
                   f"{hits} pairs resolved from memory: {', '.join(d['memory_id'] for d in decisions.values())}" if hits else "no stored decision applies",
                   target_agent="Resolver", confidence=1.0)
        return decisions

    # --- write -------------------------------------------------------------

    def remember_decision(self, a_council: str, a_name: str, b_council: str, b_name: str, verdict: str, actor: str = "human") -> dict[str, Any]:
        key = pair_key(a_council, a_name, b_council, b_name)
        text = (f"Supplier match decision: '{a_name}' ({a_council}) and '{b_name}' ({b_council}) are "
                f"{'the same organisation' if verdict == 'same' else 'different organisations'}. Decided by {actor}.")
        now = self.ctx.memory.clock()
        rec = self.ctx.memory.add(
            content=text,
            source=f"{actor}:approval-gate",
            type="factual",
            layer="long_term",
            confidence=1.0,
            tags=["decision:supplier-match", f"pair:{key}", f"verdict:{verdict}", f"council:{a_council}", f"council:{b_council}"],
            provenance=Provenance(origin="user_correction", learned_at=now, label=f"{actor} decision via ApprovalGate"),
        )
        # if an earlier decision on this pair exists, this one supersedes it (kept, penalised, never deleted)
        for m in self.ctx.memory.store.all():
            if m.id != rec.id and f"pair:{key}" in m.tags and not m.superseded_by:
                self.ctx.memory.store.update(m.id, superseded_by=rec.id)
        self.trace("remember", text, f"stored {rec.id} (long_term, confidence 1.0, ledger: create)", target_agent="Resolver", confidence=1.0,
                   memory_id=rec.id, normalised_pair=key)
        return {"memory_id": rec.id, "pair_key": key, "verdict": verdict, "content": text}

    def feedback(self, memory_id: str, kind: str) -> None:
        self.ctx.memory.feedback(memory_id, kind)
        self.trace("feedback", f"{memory_id} {kind}", "confidence adjusted per H-MEM deltas", confidence=1.0)

    def ledger_tail(self, n: int = 5) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.ctx.memory.ledger.all()[-n:]]

    @staticmethod
    def normalised(name: str) -> str:
        return normalise(name)
