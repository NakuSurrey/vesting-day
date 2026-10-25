"""Sleep cycle (AGENTS.md section 8). Preview-first: preview() computes the
full action plan and mutates nothing; execute() takes a backup snapshot first
and exposes restore(). Guardrails: superseding/current records, derived or
synthesized memories, and relationship hubs are NEVER archived.

Port of reference/src/sleepCycle.ts.
"""

from __future__ import annotations

from typing import Any, Optional

from .embeddings import cosine
from .ledger import TrustLedgerService
from .store import MemoryStoreService
from .types import DAY_MS, DEFAULTS, Clock, MemoryRecord, Provenance, SleepPreview, SleepReport

HUB_THRESHOLD = 3


class SleepCycleService:
    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Clock, actor: str) -> None:
        self._store = store
        self._ledger = ledger
        self._clock = clock
        self._actor = actor
        self._backups: dict[str, dict[str, Any]] = {}
        self._backup_seq = 0

    def preview(self) -> SleepPreview:
        now = self._clock()
        all_records = self._store.all()
        referenced: set[str] = set()
        for m in all_records:
            referenced.update(m.related_to)
            if m.supersedes:
                referenced.add(m.supersedes)
            referenced.update(m.derived_from or [])

        to_consolidate = [
            m.id
            for m in all_records
            if m.layer == "short_term" and now - m.last_accessed >= DEFAULTS.consolidation_days * DAY_MS
        ]

        to_archive: list[str] = []
        for m in all_records:
            old_enough = now - m.timestamp >= DEFAULTS.archive_min_days * DAY_MS
            low_access = m.access_count <= DEFAULTS.archive_max_access
            unreferenced = m.id not in referenced
            if not (old_enough and low_access and unreferenced):
                continue
            # Guardrails (section 8.2): never archive these three classes.
            if m.supersedes:
                continue  # superseding/current record
            if m.derived_from:
                continue  # derived/synthesized memory
            if len(m.related_to) >= HUB_THRESHOLD:
                continue  # relationship hub
            to_archive.append(m.id)

        to_synthesize: list[list[str]] = []
        used: set[str] = set()
        for i in range(len(all_records)):
            if all_records[i].id in used:
                continue
            group = [all_records[i]]
            for j in range(i + 1, len(all_records)):
                if all_records[j].id in used:
                    continue
                if cosine(all_records[i].embedding, all_records[j].embedding) >= DEFAULTS.synthesis_cosine:
                    group.append(all_records[j])
            if len(group) >= 2:
                for g in group:
                    used.add(g.id)
                to_synthesize.append([g.id for g in group])

        return SleepPreview(to_consolidate=to_consolidate, to_archive=to_archive, to_synthesize=to_synthesize)

    def execute(self, preview: Optional[SleepPreview] = None) -> SleepReport:
        plan = preview if preview is not None else self.preview()
        self._backup_seq += 1
        backup_id = f"backup-{self._backup_seq}"
        self._backups[backup_id] = self._store.snapshot_all()
        action_log = [f"backup {backup_id} created"]

        for rid in plan.to_consolidate:
            if self._store.get(rid) is None:
                continue
            self._store.promote(rid, "long_term")
            self._ledger.log(rid, "sleep_consolidate", self._actor, details={"from": "short_term", "to": "long_term"})
            action_log.append(f"consolidated {rid}")

        for rid in plan.to_archive:
            m = self._store.get(rid)
            if m is None:
                continue
            self._ledger.log(
                rid, "sleep_archive", self._actor,
                details={"age": self._clock() - m.timestamp, "accessCount": m.access_count},
            )
            self._store.delete(rid, "sleep archive")
            action_log.append(f"archived {rid}")

        synthesized = 0
        for group in plan.to_synthesize:
            members: list[MemoryRecord] = [m for m in (self._store.get(rid) for rid in group) if m is not None]
            if len(members) < 2:
                continue
            tags: dict[str, None] = {}
            for m in members:
                for t in m.tags:
                    tags[t] = None
            merged = self._store.add(
                content="Synthesis: " + " | ".join(m.content for m in members),
                type="factual",
                layer="long_term",
                tags=list(tags.keys()),
                confidence=max(m.confidence for m in members),
                source="sleep:synthesis",
                provenance=Provenance(
                    origin="sleep_synthesis", learned_at=self._clock(), label=f"synthesized from {len(members)} memories"
                ),
                derived_from=[m.id for m in members],
            )
            self._ledger.log(merged.id, "sleep_synthesize", self._actor, details={"sources": list(group)})
            for m in members:
                self._store.delete(m.id, "merged by sleep synthesis")
            synthesized += 1
            action_log.append(f"synthesized {merged.id} from {', '.join(group)}")

        self._store.persist()
        return SleepReport(
            backup_id=backup_id,
            consolidated=len(plan.to_consolidate),
            archived=len(plan.to_archive),
            synthesized=synthesized,
            action_log=action_log,
        )

    def restore(self, backup_id: str) -> None:
        backup = self._backups.get(backup_id)
        if backup is None:
            raise KeyError(f"H-MEM: unknown backup {backup_id}")
        self._store.restore_all(backup["records"], backup["seq"])
        self._ledger.log("*", "restore", self._actor, details={"backupId": backup_id})
