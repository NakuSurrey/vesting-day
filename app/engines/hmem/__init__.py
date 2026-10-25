"""Python port of the Meterless H-MEM engine (reference: github.com/Meterless/Meterless,
engines/hmem, Apache-2.0). Spec: AGENTS.md. Conformance: tests/test_hmem_conformance.py
against the unmodified upstream vectors in third_party/hmem/vectors.json.
"""

from .embeddings import cosine, embed, jaccard, tokenize
from .engine import HMEM
from .mining import parse_strict_json_array
from .types import (
    DEFAULTS,
    FEEDBACK_DELTAS,
    ConflictRecord,
    DreamProposal,
    LedgerEntry,
    MemoryRecord,
    Provenance,
    QueryResult,
    RetrievedMemory,
    SleepPreview,
    SleepReport,
    clamp01,
    snapshot,
)

__all__ = [
    "HMEM", "DEFAULTS", "FEEDBACK_DELTAS", "ConflictRecord", "DreamProposal", "LedgerEntry",
    "MemoryRecord", "Provenance", "QueryResult", "RetrievedMemory", "SleepPreview", "SleepReport",
    "clamp01", "snapshot", "cosine", "embed", "jaccard", "tokenize", "parse_strict_json_array",
]
