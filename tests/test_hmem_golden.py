"""Golden test: our Python H-MEM port must reproduce the upstream TypeScript
reference bit-for-bit on fixed scenarios.

tests/golden/hmem_reference_output.json was produced by running the Meterless
reference implementation (scripts/xcheck/reference_scenarios.ts). This test
replays the identical scenarios through the Python engine and compares
tokens, embeddings, cosine, ranking, scores, reinjection text, entities and
conflict resolution. No Node is needed at test time.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engines.hmem import HMEM, cosine, embed, tokenize

GOLDEN = json.loads((Path(__file__).resolve().parent / "golden" / "hmem_reference_output.json").read_text())
T0 = 1750000000000
TEXTS = [
    "we deploy the api with docker on mondays",
    "Biffa Waste Services Ltd supplies Woking and Guildford",
    "always enable telemetry uploads for diagnostics",
    "never enable telemetry uploads for diagnostics",
    "Council Tax Support band cap is Band D in Woking from April 2025",
]


def test_tokenize_and_embed_match_reference():
    for t in TEXTS:
        assert tokenize(t) == GOLDEN["tokens"][t]
        ours = embed(t)
        theirs = GOLDEN["embed"][t]
        assert len(ours) == len(theirs) == 64
        assert max(abs(x - y) for x, y in zip(ours, theirs)) < 1e-12


def test_cosine_matches_reference():
    assert abs(cosine(embed(TEXTS[2]), embed(TEXTS[3])) - GOLDEN["cosine"]["a2b3"]) < 1e-12


def test_query_ranking_scores_and_context_match_reference():
    h = HMEM(clock=lambda: T0)
    m1 = h.add(content=TEXTS[0], confidence=0.9, layer="long_term", source="x")
    m2 = h.add(content="we deploy the api with docker on fridays", confidence=0.9, layer="long_term", source="x")
    m3 = h.add(content=TEXTS[1], confidence=0.8, layer="working", type="factual", source="x")
    m2.superseded_by = m1.id
    q = h.query("when do we deploy the api with docker", threshold=0, top_n=10)
    assert [rm.memory.id for rm in q.memories] == GOLDEN["query"]["ids"]
    for k, v in GOLDEN["query"]["scores"].items():
        assert abs(q.trace.scores[k] - v) < 1e-9
    assert q.context == GOLDEN["query"]["context"]
    assert q.trace.strategy == GOLDEN["query"]["strategy"]
    assert m3.entities == GOLDEN["entities"]["m3"]
    assert m3.domain == GOLDEN["entities"]["domain"]
    assert m3.namespace == GOLDEN["entities"]["namespace"]


def test_conflict_detection_and_resolution_match_reference():
    h = HMEM(clock=lambda: T0)
    a = h.add(content=TEXTS[2], confidence=0.95, source="x")
    b = h.add(content=TEXTS[3], confidence=0.2, source="x")
    found = h.conflicts.scan()
    assert len(found) == GOLDEN["conflict"]["n"]
    assert abs(found[0].confidence - GOLDEN["conflict"]["confidence"]) < 1e-12
    assert h.conflicts.auto_resolve(found[0]) == GOLDEN["conflict"]["outcome"]
    assert [h.store.get(a.id).superseded_by, h.store.get(b.id).superseded_by] == GOLDEN["conflict"]["loserSupersededBy"]
