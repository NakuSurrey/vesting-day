"""Canonical H-MEM shapes.

Python port of the Meterless H-MEM reference (engines/hmem/reference/src/types.ts).
Attribute names are snake_case in Python; snapshot() emits the canonical camelCase
field names from the Meterless reference, so ledger and state files match it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

MemoryType = Literal["personal", "factual", "preference", "general"]
MemoryLayer = Literal["short_term", "working", "long_term"]
ProvenanceOrigin = Literal[
    "chat_message", "user_correction", "file_save", "file_open", "file_edit",
    "model_response", "plan_completion", "document", "manual", "dream", "sleep_synthesis",
]
MiningEventType = Literal[
    "chat_message", "user_correction", "file_save", "file_open", "file_edit",
    "model_response", "plan_completion",
]
LedgerAction = Literal[
    "create", "read", "update", "delete", "feedback", "promote", "demote", "merge",
    "conflict_detected", "conflict_resolved",
    "sleep_consolidate", "sleep_archive", "sleep_synthesize",
    "dream_proposed", "dream_approved", "dream_rejected", "restore",
]
FeedbackKind = Literal["helpful", "not_helpful", "wrong"]
DreamProposalType = Literal["insight", "domain", "invariant"]

FEEDBACK_DELTAS: dict[str, float] = {"helpful": 0.05, "not_helpful": -0.03, "wrong": -0.2}

DAY_MS = 24 * 60 * 60 * 1000


@dataclass
class Defaults:
    retrieval_top_n: int = 5
    retrieval_threshold: float = 0.35  # on the final score, after the confidence multiplier
    consolidation_days: int = 7
    archive_min_days: int = 30
    archive_max_access: int = 2
    synthesis_cosine: float = 0.82
    dream_cluster_min_size: int = 2
    dream_relatedness: float = 0.35
    max_dream_proposals_per_type: int = 8
    conflict_auto_resolve_gate: float = 0.7
    entity_cap: int = 10
    related_cap: int = 5
    recency_days: int = 14


DEFAULTS = Defaults()


def clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class Provenance:
    origin: str
    learned_at: int
    label: str
    refs: Optional[list[str]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"origin": self.origin, "learnedAt": self.learned_at, "label": self.label}
        if self.refs is not None:
            d["refs"] = list(self.refs)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Provenance":
        return Provenance(origin=d["origin"], learned_at=d["learnedAt"], label=d["label"], refs=d.get("refs"))


# Python attribute -> canonical field name in the Meterless reference.
CANONICAL_FIELDS: dict[str, str] = {
    "id": "id",
    "content": "content",
    "type": "type",
    "layer": "layer",
    "timestamp": "timestamp",
    "last_accessed": "lastAccessed",
    "access_count": "accessCount",
    "tags": "tags",
    "embedding": "embedding",
    "score": "score",
    "confidence": "confidence",
    "source": "source",
    "provenance": "provenance",
    "chat_id": "chatId",
    "mission_id": "missionId",
    "goal_run_id": "goalRunId",
    "domain": "domain",
    "namespace": "namespace",
    "entities": "entities",
    "related_to": "relatedTo",
    "supersedes": "supersedes",
    "superseded_by": "supersededBy",
    "derived_from": "derivedFrom",
}
PYTHON_FIELDS: dict[str, str] = {v: k for k, v in CANONICAL_FIELDS.items()}


@dataclass
class MemoryRecord:
    id: str
    content: str
    type: str
    layer: str
    timestamp: int
    last_accessed: int
    access_count: int
    tags: list[str]
    embedding: list[float]
    confidence: float          # mandatory
    source: str                # mandatory; construction rejects records without it
    provenance: Provenance     # mandatory for new writes
    domain: str
    namespace: str
    entities: list[str]        # cap 10
    related_to: list[str]      # cap 5
    score: Optional[float] = None
    chat_id: Optional[str] = None
    mission_id: Optional[str] = None
    goal_run_id: Optional[str] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None  # set by conflict resolution; drives the retrieval penalty
    derived_from: Optional[list[str]] = None

    def to_dict(self, include_embedding: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for py_name, spec_name in CANONICAL_FIELDS.items():
            if py_name == "embedding" and not include_embedding:
                continue
            value = getattr(self, py_name)
            if value is None:
                continue
            if py_name == "provenance":
                value = value.to_dict()
            elif isinstance(value, list):
                value = list(value)
            out[spec_name] = value
        return out

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MemoryRecord":
        kwargs: dict[str, Any] = {}
        for spec_name, value in d.items():
            py_name = PYTHON_FIELDS.get(spec_name)
            if py_name is None:
                continue
            if py_name == "provenance":
                value = Provenance.from_dict(value)
            kwargs[py_name] = value
        return MemoryRecord(**kwargs)


def snapshot(r: MemoryRecord) -> dict[str, Any]:
    """Deep copy of a record minus the embedding, in canonical field names."""
    return copy.deepcopy(r.to_dict(include_embedding=False))


@dataclass
class LedgerEntry:
    memory_id: str
    action: str
    actor: str
    timestamp: int
    previous_state: Optional[dict[str, Any]] = None
    new_state: Optional[dict[str, Any]] = None
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "memoryId": self.memory_id,
            "action": self.action,
            "actor": self.actor,
            "timestamp": self.timestamp,
        }
        if self.previous_state is not None:
            d["previousState"] = self.previous_state
        if self.new_state is not None:
            d["newState"] = self.new_state
        if self.details is not None:
            d["details"] = self.details
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "LedgerEntry":
        return LedgerEntry(
            memory_id=d["memoryId"],
            action=d["action"],
            actor=d["actor"],
            timestamp=d["timestamp"],
            previous_state=d.get("previousState"),
            new_state=d.get("newState"),
            details=d.get("details"),
        )


@dataclass
class DreamProposal:
    id: str
    type: str
    content: str
    derived_from: list[str]
    status: str = "proposed"  # proposed | approved | rejected
    suggested_domain: Optional[str] = None


@dataclass
class SleepPreview:
    to_consolidate: list[str] = field(default_factory=list)
    to_archive: list[str] = field(default_factory=list)
    to_synthesize: list[list[str]] = field(default_factory=list)


@dataclass
class SleepReport:
    backup_id: str
    consolidated: int
    archived: int
    synthesized: int
    action_log: list[str]


@dataclass
class ConflictRecord:
    id: str
    memory_a: str
    memory_b: str
    reason: str
    confidence: float
    resolved: bool = False
    resolution: Optional[str] = None  # keep_a | keep_b | keep_both | merge | delete_both


@dataclass
class RetrievedMemory:
    memory: MemoryRecord
    relevance: float


@dataclass
class QueryTrace:
    retrieval_reason: str
    strategy: str  # minimal | personal | comprehensive
    scores: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {"retrievalReason": self.retrieval_reason, "strategy": self.strategy, "scores": dict(self.scores)}


@dataclass
class QueryResult:
    memories: list[RetrievedMemory]
    context: str
    trace: QueryTrace


Clock = Callable[[], int]
MinerFn = Callable[[str], str]
