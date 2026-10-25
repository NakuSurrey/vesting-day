"""H-MEM facade. Deterministic, zero runtime dependencies, in-memory with
optional JSON persistence (state.json + ledger.jsonl in persist_dir).

Port of reference/src/index.ts. The surface mirrors HOW_TO_USE_H-MEM.md:
add(), mine(), query(), feedback(), plus the service objects
store / ledger / mining / retrieval / conflicts / sleep / dreaming.
"""

from __future__ import annotations

import time
from typing import Optional

from .conflicts import ConflictDetectionService
from .dreaming import DreamingService
from .ledger import TrustLedgerService
from .mining import MemoryMiningService
from .retrieval import MemoryRetrievalService
from .sleep import SleepCycleService
from .store import MemoryStoreService
from .types import Clock, MemoryRecord, MinerFn, Provenance, QueryResult


def _now_ms() -> int:
    return int(time.time() * 1000)


class HMEM:
    def __init__(
        self,
        clock: Optional[Clock] = None,
        persist_dir: Optional[str] = None,
        actor: str = "system",
        miner_fn: Optional[MinerFn] = None,
    ) -> None:
        self.clock: Clock = clock or _now_ms
        self.ledger = TrustLedgerService(self.clock, persist_dir)
        self.store = MemoryStoreService(self.clock, self.ledger, actor, persist_dir)
        self.mining = MemoryMiningService(self.store, self.clock, miner_fn)
        self.retrieval = MemoryRetrievalService(self.store, self.ledger, self.clock, actor)
        self.conflicts = ConflictDetectionService(self.store, self.ledger, self.clock, actor)
        self.sleep = SleepCycleService(self.store, self.ledger, self.clock, actor)
        self.dreaming = DreamingService(self.store, self.ledger, self.clock, actor)

    # Convenience surface.
    def add(
        self,
        content: str,
        source: str,
        type: str = "general",
        layer: str = "working",
        tags: Optional[list[str]] = None,
        confidence: Optional[float] = None,
        provenance: Optional[Provenance] = None,
        chat_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        goal_run_id: Optional[str] = None,
        supersedes: Optional[str] = None,
        derived_from: Optional[list[str]] = None,
    ) -> MemoryRecord:
        return self.store.add(
            content=content,
            source=source,
            type=type,
            layer=layer,
            tags=tags,
            confidence=confidence,
            provenance=provenance,
            chat_id=chat_id,
            mission_id=mission_id,
            goal_run_id=goal_run_id,
            supersedes=supersedes,
            derived_from=derived_from,
        )

    def mine(self, event: str, text: str, chat_id: Optional[str] = None) -> list[MemoryRecord]:
        return self.mining.mine_interaction(event, text, chat_id=chat_id)

    def query(
        self,
        query: str,
        top_n: Optional[int] = None,
        threshold: Optional[float] = None,
        chat_id: Optional[str] = None,
    ) -> QueryResult:
        return self.retrieval.query(query, top_n=top_n, threshold=threshold, chat_id=chat_id)

    def feedback(self, memory_id: str, kind: str) -> None:
        self.retrieval.feedback(memory_id, kind)
