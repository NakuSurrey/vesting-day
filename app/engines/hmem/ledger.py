"""Append-only trust ledger (AGENTS.md section 9.1). Entries are never mutated
or deleted. history() reconstructs a memory's full change record from the
previousState/newState snapshots carried on each entry.

Port of reference/src/trustLedger.ts. When persist_dir is set, every entry is
appended to ledger.jsonl - the file we ship to logs/ as judge evidence.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .types import Clock, LedgerEntry


class TrustLedgerService:
    def __init__(self, clock: Clock, persist_dir: Optional[str] = None) -> None:
        self._clock = clock
        self._entries: list[LedgerEntry] = []
        self._file: Optional[str] = None
        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)
            self._file = os.path.join(persist_dir, "ledger.jsonl")
            if os.path.exists(self._file):
                with open(self._file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            self._entries.append(LedgerEntry.from_dict(json.loads(line)))

    def log(
        self,
        memory_id: str,
        action: str,
        actor: str,
        previous_state: Optional[dict[str, Any]] = None,
        new_state: Optional[dict[str, Any]] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            memory_id=memory_id,
            action=action,
            actor=actor,
            timestamp=self._clock(),
            previous_state=previous_state,
            new_state=new_state,
            details=details,
        )
        self._entries.append(entry)
        if self._file:
            with open(self._file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return entry

    def history(self, memory_id: str) -> list[LedgerEntry]:
        return [e for e in self._entries if e.memory_id == memory_id]

    def all(self) -> list[LedgerEntry]:
        return list(self._entries)

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self._entries:
            out[e.action] = out.get(e.action, 0) + 1
        return out
