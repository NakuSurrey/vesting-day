"""Deterministic embedder: FNV-1a hash per token into a 64-dim vector, summed
and L2-normalized. Pure function of the input text, so retrieval scores are
reproducible across runs and machines - and credential-free, which is what
keeps SAMPLE_MODE and the conformance suite runnable with no model.

Faithful port of reference/src/embeddings.ts (Math.imul semantics kept).
"""

from __future__ import annotations

import math
import re
from typing import Iterable

DIM = 64
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def tokenize(text: str) -> list[str]:
    cleaned = _NON_ALNUM.sub(" ", text.lower())
    return [t for t in _WS.split(cleaned) if len(t) > 1]


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in tokenize(text):
        h = fnv1a(token)
        idx = h % DIM
        sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
        mag = 1.0 + ((h >> 16) % 8) / 8.0
        vec[idx] += sign * mag
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    # both vectors are unit-length
    return sum(x * y for x, y in zip(a, b))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)
