"""Acquisition pipeline. The model-free fallback path is
the DEFAULT: heuristic sentence extraction preserves capture continuity with
no model available. An optional miner_fn hook accepts an extraction prompt and
returns a strict JSON array of memory strings; its output is parsed leniently
(markdown fences stripped, format noise tolerated).

Port of reference/src/memoryMining.ts. The hook is a plain callable so the
engine stays usable from synchronous code and from SAMPLE_MODE with no model.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .store import MemoryStoreService
from .types import Clock, MemoryRecord, MinerFn, Provenance

EVENT_TYPE_MAP: dict[str, str] = {
    "chat_message": "general",
    "user_correction": "preference",
    "file_save": "factual",
    "file_open": "general",
    "file_edit": "factual",
    "model_response": "factual",
    "plan_completion": "factual",
}

_SIGNAL = re.compile(
    r"\b(prefer|always|never|decided|chose|choose|use|because|instead|must|should|important|remember)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"```\s*$")


class MemoryMiningService:
    def __init__(self, store: MemoryStoreService, clock: Clock, miner_fn: Optional[MinerFn] = None) -> None:
        self._store = store
        self._clock = clock
        self._miner_fn = miner_fn

    def mine_interaction(
        self,
        event: str,
        text: str,
        chat_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> list[MemoryRecord]:
        if event not in EVENT_TYPE_MAP:
            raise ValueError(f"H-MEM: unknown mining event {event}")
        candidates = self._mine_with_model(event, text) if self._miner_fn else self.mine_model_free(text)
        default_layer = "working" if self._miner_fn else "short_term"
        out: list[MemoryRecord] = []
        for content in candidates:
            out.append(
                self._store.add(
                    content=content,
                    type=EVENT_TYPE_MAP[event],
                    layer=layer or default_layer,
                    tags=[f"event:{event}"],
                    source=f"interaction:{event}",
                    provenance=Provenance(origin=event, learned_at=self._clock(), label=f"mined from {event}"),
                    chat_id=chat_id,
                )
            )
        return out

    def mine_document(self, file_name: str, text: str) -> list[MemoryRecord]:
        truncated = text[:8000]  # safe token window
        candidates = self._mine_with_model("file_save", truncated) if self._miner_fn else self.mine_model_free(truncated)
        return [
            self._store.add(
                content=content,
                type="factual",
                layer="working",
                tags=["document", f"file:{file_name}"],
                source=f"document:{file_name}",
            )
            for content in candidates
        ]

    # 4.3: no-model fallback. Concise direct summaries as short-term memories.
    def mine_model_free(self, text: str) -> list[str]:
        out: list[str] = []
        for s in _SPLIT.split(text):
            s = s.strip()
            if 20 <= len(s) <= 300 and _SIGNAL.search(s):
                out.append(s)
        return out[:10]

    def _mine_with_model(self, event: str, text: str) -> list[str]:
        assert self._miner_fn is not None
        prompt = f"Extract durable memories from this {event} as a strict JSON array of strings:\n\n{text}"
        return parse_strict_json_array(self._miner_fn(prompt))


# Lenient parsing: strip markdown fences, tolerate minor noise.
def parse_strict_json_array(raw: str) -> list[str]:
    cleaned = raw.strip()
    cleaned = _FENCE_OPEN.sub("", cleaned)
    cleaned = _FENCE_CLOSE.sub("", cleaned).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [x for x in parsed if isinstance(x, str) and len(x.strip()) >= 5]
