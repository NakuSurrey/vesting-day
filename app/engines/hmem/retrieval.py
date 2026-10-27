"""Hybrid retrieval and reinjection. The canonical formula:

    raw = 0.35*semantic + 0.20*keyword + 0.10*tag + 0.10*domain
        + 0.15*entity   + 0.05*layer   + 0.05*recency - 0.20*superseded
    score = clamp01(raw) * confidence          <- confidence multiplies AFTER the sum

keyword = Jaccard of the top-8 query tokens vs memory tokens.
layer weights: long_term 1.0, working 0.8, short_term 0.6.
recency = exponential decay on lastAccessed, 14-day time constant.
superseded records are penalized, never deleted or filtered.
Threshold 0.35 applies to the FINAL score; top N = 5.

Port of reference/src/memoryRetrieval.ts.
"""

from __future__ import annotations

import math
from typing import Optional

from .embeddings import cosine, embed, jaccard, tokenize
from .ledger import TrustLedgerService
from .store import MemoryStoreService
from .types import (
    DAY_MS,
    DEFAULTS,
    FEEDBACK_DELTAS,
    Clock,
    MemoryRecord,
    QueryResult,
    QueryTrace,
    RetrievedMemory,
    clamp01,
    snapshot,
)

LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}


class MemoryRetrievalService:
    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Clock, actor: str) -> None:
        self._store = store
        self._ledger = ledger
        self._clock = clock
        self._actor = actor

    def score_one(self, memory: MemoryRecord, query: str) -> float:
        q_emb = embed(query)
        q_tokens = tokenize(query)[:8]
        q_entities = self._store.extract_entities(query)
        q_domain = self._store.classify_domain(query, [], "general")
        return self._score(memory, q_emb, q_tokens, q_entities, q_domain)

    def _score(
        self,
        m: MemoryRecord,
        q_emb: list[float],
        q_tokens: list[str],
        q_entities: list[str],
        q_domain: str,
    ) -> float:
        semantic = clamp01(cosine(q_emb, m.embedding))
        keyword = jaccard(q_tokens, tokenize(m.content))
        tag = jaccard(q_tokens, [t.lower() for t in m.tags])
        domain = 1.0 if m.domain == q_domain else 0.0
        entity = jaccard(q_entities, m.entities)
        layer = LAYER_WEIGHT[m.layer]
        age_days = (self._clock() - m.last_accessed) / DAY_MS
        recency = math.exp(-age_days / DEFAULTS.recency_days)
        superseded = 1.0 if m.superseded_by else 0.0
        raw = (
            0.35 * semantic + 0.2 * keyword + 0.1 * tag + 0.1 * domain
            + 0.15 * entity + 0.05 * layer + 0.05 * recency - 0.2 * superseded
        )
        return clamp01(raw) * m.confidence

    def query(
        self,
        query: str,
        top_n: Optional[int] = None,
        threshold: Optional[float] = None,
        chat_id: Optional[str] = None,
    ) -> QueryResult:
        q_emb = embed(query)
        q_tokens = tokenize(query)[:8]
        q_entities = self._store.extract_entities(query)
        q_domain = self._store.classify_domain(query, [], "general")
        thr = DEFAULTS.retrieval_threshold if threshold is None else threshold
        n = DEFAULTS.retrieval_top_n if top_n is None else top_n

        scored: list[RetrievedMemory] = []
        for m in self._store.all():
            if chat_id and m.chat_id and m.chat_id != chat_id:
                continue
            s = self._score(m, q_emb, q_tokens, q_entities, q_domain)
            if s >= thr:
                scored.append(RetrievedMemory(memory=m, relevance=s))
        scored.sort(key=lambda rm: (-rm.relevance, rm.memory.id))
        top = scored[:n]

        for rm in top:
            self._store.touch(rm.memory.id)
            self._ledger.log(rm.memory.id, "read", self._actor, details={"query": query})

        if len(top) <= 1:
            strategy = "minimal"
        elif any(rm.memory.type in ("personal", "preference") for rm in top):
            strategy = "personal"
        else:
            strategy = "comprehensive"

        return QueryResult(
            memories=top,
            context=self.format_reinjection(top),
            trace=QueryTrace(
                retrieval_reason=f'hybrid ranking for "{query}" (domain: {q_domain})',
                strategy=strategy,
                scores={rm.memory.id: round(rm.relevance, 4) for rm in top},
            ),
        )

    # Domain-grouped reinjection blocks with layer markers and entities.
    def format_reinjection(self, items: list[RetrievedMemory]) -> str:
        if not items:
            return ""
        by_domain: dict[str, list[RetrievedMemory]] = {}
        for it in items:
            by_domain.setdefault(it.memory.domain, []).append(it)
        lines = ["[MEMORY CONTEXT]"]
        for domain in sorted(by_domain):
            lines.append(f"## {domain}")
            for rm in by_domain[domain]:
                mem = rm.memory
                marker = "LT" if mem.layer == "long_term" else "WK" if mem.layer == "working" else "ST"
                ents = f" (entities: {', '.join(mem.entities)})" if mem.entities else ""
                lines.append(f"- [{marker}] {mem.content}{ents} <{mem.id}>")
        lines.append("[/MEMORY CONTEXT]")
        return "\n".join(lines)

    # How each feedback signal changes a memory's confidence and access count.
    def feedback(self, memory_id: str, kind: str) -> None:
        m = self._store.get(memory_id)
        if m is None:
            raise KeyError(f"H-MEM: unknown memory id {memory_id}")
        if kind not in FEEDBACK_DELTAS:
            raise ValueError(f"H-MEM: unknown feedback kind {kind}")
        prev = snapshot(m)
        if kind == "helpful":
            m.access_count += 1
        m.confidence = clamp01(m.confidence + FEEDBACK_DELTAS[kind])
        if kind == "wrong" and "review" not in m.tags:
            m.tags.append("review")
        self._ledger.log(
            memory_id,
            "feedback",
            self._actor,
            previous_state=prev,
            new_state=snapshot(m),
            details={"kind": kind, "delta": FEEDBACK_DELTAS[kind]},
        )
        self._store.persist()
