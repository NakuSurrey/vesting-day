"""Dreaming: constructive synthesis with an approval
boundary. Proposals are NEVER auto-materialized; only approve() turns one into
durable memory, with derivedFrom lineage.

Port of reference/src/dreaming.ts.
"""

from __future__ import annotations

from typing import Optional

from .embeddings import cosine, jaccard
from .ledger import TrustLedgerService
from .store import MemoryStoreService
from .types import DEFAULTS, Clock, DreamProposal, MemoryRecord, Provenance


class DreamingService:
    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Clock, actor: str) -> None:
        self._store = store
        self._ledger = ledger
        self._clock = clock
        self._actor = actor
        self._proposals: dict[str, DreamProposal] = {}
        self._seq = 0

    # Multi-signal relatedness: content similarity, tag overlap, shared domain/type, entity overlap.
    def _relatedness(self, a: MemoryRecord, b: MemoryRecord) -> float:
        return (
            0.5 * max(0.0, cosine(a.embedding, b.embedding))
            + 0.2 * jaccard(a.tags, b.tags)
            + 0.1 * (1.0 if a.domain == b.domain else 0.0)
            + 0.2 * jaccard(a.entities, b.entities)
        )

    def _cluster(self) -> list[list[MemoryRecord]]:
        all_records = self._store.all()
        used: set[str] = set()
        clusters: list[list[MemoryRecord]] = []
        for seed in all_records:
            if seed.id in used:
                continue
            group = [seed]
            for other in all_records:
                if other.id == seed.id or other.id in used:
                    continue
                if self._relatedness(seed, other) >= DEFAULTS.dream_relatedness:
                    group.append(other)
            if len(group) >= DEFAULTS.dream_cluster_min_size:
                for g in group:
                    used.add(g.id)
                clusters.append(group)
        return clusters

    def dream(self) -> list[DreamProposal]:
        created: list[DreamProposal] = []

        def propose(type: str, content: str, derived_from: list[str], suggested_domain: Optional[str] = None) -> None:
            self._seq += 1
            proposal = DreamProposal(
                id=f"dream-{self._seq}",
                type=type,
                content=content,
                derived_from=list(derived_from),
                status="proposed",
                suggested_domain=suggested_domain,
            )
            self._proposals[proposal.id] = proposal
            created.append(proposal)
            self._ledger.log(proposal.id, "dream_proposed", self._actor, details={"type": type, "derivedFrom": list(derived_from)})

        # Insights from clusters.
        insights = 0
        for cluster in self._cluster():
            if insights >= DEFAULTS.max_dream_proposals_per_type:
                break
            domains = "/".join(dict.fromkeys(m.domain for m in cluster))
            propose(
                "insight",
                f"Across {len(cluster)} related memories ({domains}): " + " + ".join(m.content for m in cluster),
                [m.id for m in cluster],
            )
            insights += 1

        # Domain suggestions for uncategorized memories.
        domains_n = 0
        for m in self._store.all():
            if domains_n >= DEFAULTS.max_dream_proposals_per_type:
                break
            if m.domain != "general":
                continue
            suggested = self._store.classify_domain(m.content, m.tags, m.type)
            if suggested != "general":
                propose("domain", f'Reclassify "{m.content[:60]}" as {suggested}', [m.id], suggested_domain=suggested)
                domains_n += 1

        # Invariants from preference/personal/correction signals.
        invariants = 0
        prefs = [
            m for m in self._store.all()
            if m.type in ("preference", "personal") or "event:user_correction" in m.tags
        ]
        by_domain: dict[str, list[MemoryRecord]] = {}
        for p in prefs:
            by_domain.setdefault(p.domain, []).append(p)
        for domain, items in by_domain.items():
            if invariants >= DEFAULTS.max_dream_proposals_per_type:
                break
            if len(items) < 2:
                continue
            propose("invariant", f"Stable pattern in {domain}: " + "; ".join(m.content for m in items), [m.id for m in items])
            invariants += 1

        return created

    def pending(self) -> list[DreamProposal]:
        return [p for p in self._proposals.values() if p.status == "proposed"]

    def approve(self, proposal_id: str) -> Optional[MemoryRecord]:
        p = self._proposals.get(proposal_id)
        if p is None or p.status != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        p.status = "approved"
        self._ledger.log(proposal_id, "dream_approved", self._actor, details={"type": p.type})

        if p.type == "domain":
            for rid in p.derived_from:
                if self._store.get(rid) is not None and p.suggested_domain:
                    self._store.update(rid, domain=p.suggested_domain)
            return None
        # insight -> long-term factual; invariant -> long-term preference. Both carry lineage.
        return self._store.add(
            content=p.content,
            type="factual" if p.type == "insight" else "preference",
            layer="long_term",
            tags=[f"dream:{p.type}"],
            confidence=0.75,
            source="dreaming",
            provenance=Provenance(origin="dream", learned_at=self._clock(), label=f"approved {p.type} proposal"),
            derived_from=p.derived_from,
        )

    def reject(self, proposal_id: str) -> None:
        p = self._proposals.get(proposal_id)
        if p is None or p.status != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        p.status = "rejected"  # logged, not materialized
        self._ledger.log(proposal_id, "dream_rejected", self._actor, details={"type": p.type})
