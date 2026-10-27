"""Tiered memory store with enrichment.

A record with no source is rejected by construction. Enrichment runs on every
add: domain classification, namespace, entity extraction (cap 10), relatedTo
discovery (cap 5, bidirectional), supersedes detection.

Port of reference/src/memoryStore.ts.
"""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Optional

from .embeddings import cosine, embed, tokenize
from .ledger import TrustLedgerService
from .types import DEFAULTS, Clock, MemoryRecord, Provenance, clamp01, snapshot

TECH_TERMS = [
    "react", "python", "typescript", "javascript", "rust", "sqlite", "postgres", "indexeddb",
    "node", "docker", "graphql", "redis", "webrtc", "tauri", "electron", "llm", "embedding",
]
# Insertion order matters: ties keep the first domain, as in the reference.
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "tech": ["code", "bug", "api", "database", "deploy", "framework", "library", "server", *TECH_TERMS],
    "work": ["meeting", "deadline", "client", "project", "sprint", "review", "report"],
    "personal": ["family", "hobby", "prefer", "like", "dislike", "morning", "evening"],
}
_CAPITALIZED = re.compile(r"\b([A-Z][a-zA-Z]{2,})\b")
_CORRECTION = re.compile(r"\b(actually|instead|no longer|not anymore|changed to|correction)\b", re.IGNORECASE)
_STOP = {"the", "this", "that", "with"}


class MemoryStoreService:
    def __init__(
        self,
        clock: Clock,
        ledger: TrustLedgerService,
        actor: str,
        persist_dir: Optional[str] = None,
    ) -> None:
        self._clock = clock
        self._ledger = ledger
        self._actor = actor
        self._records: dict[str, MemoryRecord] = {}
        self._seq = 0
        self._state_file: Optional[str] = None
        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)
            self._state_file = os.path.join(persist_dir, "state.json")
            if os.path.exists(self._state_file):
                with open(self._state_file, "r", encoding="utf-8") as fh:
                    saved = json.load(fh)
                self._seq = int(saved.get("seq", 0))
                for r in saved.get("records", []):
                    rec = MemoryRecord.from_dict(r)
                    self._records[rec.id] = rec

    # -- persistence ---------------------------------------------------------

    def persist(self) -> None:
        if not self._state_file:
            return
        records = sorted(self._records.values(), key=lambda r: r.id)
        payload = {"seq": self._seq, "records": [r.to_dict() for r in records]}
        with open(self._state_file, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    # -- CRUD ----------------------------------------------------------------

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
        if source is None or str(source).strip() == "":
            raise ValueError(
                "H-MEM: a memory record with no source must be rejected by construction"
            )
        now = self._clock()
        self._seq += 1
        rid = f"mem-{self._seq}"
        tag_list = list(tags or [])
        domain = self.classify_domain(content, tag_list, type)
        record = MemoryRecord(
            id=rid,
            content=content,
            type=type,
            layer=layer,
            timestamp=now,
            last_accessed=now,
            access_count=0,
            tags=tag_list,
            embedding=embed(content),
            confidence=clamp01(0.7 if confidence is None else confidence),
            source=source,
            provenance=provenance or Provenance(origin="manual", learned_at=now, label=source),
            chat_id=chat_id,
            mission_id=mission_id,
            goal_run_id=goal_run_id,
            domain=domain,
            namespace=self._namespace(domain, type),
            entities=self.extract_entities(content),
            related_to=[],
            supersedes=supersedes,
            derived_from=list(derived_from) if derived_from is not None else None,
        )
        self._discover_relationships(record)
        self._records[rid] = record
        self._ledger.log(rid, "create", self._actor, new_state=snapshot(record))
        self.persist()
        return record

    def get(self, rid: str) -> Optional[MemoryRecord]:
        return self._records.get(rid)

    def all(self) -> list[MemoryRecord]:
        return list(self._records.values())

    def update(self, rid: str, **patch: Any) -> MemoryRecord:
        rec = self._must_get(rid)
        prev = snapshot(rec)
        for key, value in patch.items():
            if not hasattr(rec, key):
                raise AttributeError(f"H-MEM: unknown field {key}")
            setattr(rec, key, value)
        self._ledger.log(rid, "update", self._actor, previous_state=prev, new_state=snapshot(rec))
        self.persist()
        return rec

    def delete(self, rid: str, reason: str) -> None:
        rec = self._must_get(rid)
        del self._records[rid]
        self._ledger.log(rid, "delete", self._actor, previous_state=snapshot(rec), details={"reason": reason})
        self.persist()

    def touch(self, rid: str) -> None:
        rec = self._must_get(rid)
        rec.last_accessed = self._clock()
        rec.access_count += 1

    def promote(self, rid: str, layer: str) -> None:
        rec = self._must_get(rid)
        prev = snapshot(rec)
        rec.layer = layer
        self._ledger.log(rid, "promote", self._actor, previous_state=prev, new_state=snapshot(rec))
        self.persist()

    def restore_all(self, records: list[MemoryRecord], seq: int) -> None:
        self._records = {r.id: copy.deepcopy(r) for r in records}
        self._seq = seq
        self.persist()

    def snapshot_all(self) -> dict[str, Any]:
        return {"records": copy.deepcopy(list(self._records.values())), "seq": self._seq}

    def _must_get(self, rid: str) -> MemoryRecord:
        rec = self._records.get(rid)
        if rec is None:
            raise KeyError(f"H-MEM: unknown memory id {rid}")
        return rec

    # -- enrichment -----------------------------------

    def classify_domain(self, content: str, tags: list[str], type: str) -> str:
        for t in tags:
            if t.startswith("project:"):
                return t[len("project:"):]
            if t.startswith("tech:"):
                return "tech"
        tokens = set(tokenize(content))
        best = "general"
        best_score = 0
        for domain, kws in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in tokens)
            if domain == "personal" and type in ("personal", "preference"):
                score += 1
            if score > best_score:
                best = domain
                best_score = score
        return best if best_score > 0 else "general"

    @staticmethod
    def _namespace(domain: str, type: str) -> str:
        if type in ("preference", "personal"):
            bucket = "profile"
        elif type == "factual":
            bucket = "facts"
        else:
            bucket = "notes"
        return f"{domain}/{bucket}"

    def extract_entities(self, content: str) -> list[str]:
        entities: dict[str, None] = {}
        for t in tokenize(content):
            if t in TECH_TERMS:
                entities[t] = None
        for m in _CAPITALIZED.finditer(content):
            norm = m.group(1).lower()
            if norm not in _STOP:
                entities[norm] = None
        return list(entities.keys())[: DEFAULTS.entity_cap]

    def _discover_relationships(self, record: MemoryRecord) -> None:
        for other in self._records.values():
            if len(record.related_to) >= DEFAULTS.related_cap:
                break
            shared = [e for e in other.entities if e in record.entities]
            sim = cosine(record.embedding, other.embedding)
            if not record.supersedes and sim > 0.85 and _CORRECTION.search(record.content):
                record.supersedes = other.id
                continue
            if len(shared) >= 1 and other.domain == record.domain:
                record.related_to.append(other.id)
                if len(other.related_to) < DEFAULTS.related_cap and record.id not in other.related_to:
                    other.related_to.append(record.id)  # bidirectional link
