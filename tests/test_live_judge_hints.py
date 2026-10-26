"""Live-mode honesty: the model advises, a human decides, and the Critic enforces it.

The first real live run (26 Oct 2026) showed the problem these tests pin down: the match
judge said SAME for 5 borderline pairs, the flow counted them as shared (233 instead of
228) and the briefing called them "confirmed". Only a human may confirm a pair.

These tests run the real flows in live mode with a fake model and the local data layer,
so they need no network and no credentials.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.adapters.datalayer import LocalDataLayer
from app.adapters.nightshift import Completion, ModelClient
from app.agents.critic import HUMAN_ONLY_CLAIMS, SYNTHETIC_LABEL_CLAIM
from app.agents.resolver import JUDGE_SYSTEM
from app.config import Settings
from app.orchestrator import Orchestrator
from app.schemas import RunRequest

ROOT = Path(__file__).resolve().parents[1]
OVERLAP_Q = "Which suppliers do Woking, Guildford and Waverley share?"
POLICY_Q = "Where do the Council Tax Support schemes differ between Woking and Guildford?"


class FakeNemotron(ModelClient):
    """Answers like the live lane would: SAME/DIFFERENT for judge prompts, prose for drafts."""

    badge = "fake/nemotron"

    def __init__(self, first_draft: str, second_draft: str, same_every: int = 2) -> None:
        self.first_draft, self.second_draft, self.same_every = first_draft, second_draft, same_every
        self.judge_calls = 0
        self.draft_prompts: list[str] = []

    def complete(self, system: str, user: str, max_tokens: int = 768, temperature: float = 0.1) -> Completion:
        if system == JUDGE_SYSTEM:
            self.judge_calls += 1
            text = "SAME" if self.judge_calls % self.same_every else "DIFFERENT"
        else:
            self.draft_prompts.append(user)
            text = self.second_draft if "rejected by the Critic" in user else self.first_draft
        return Completion(text=text, model=self.badge, receipt_id=f"rcpt_fake_{self.judge_calls + len(self.draft_prompts)}", provider="fake", usage={})


def _orch(tmp_path: Path, model: ModelClient | None, sample: bool) -> Orchestrator:
    cfg = Settings()
    cfg.sample_mode = sample
    cfg.companies_house_api_key = ""
    if not sample:   # live mode needs both services configured; the fakes below stand in for them
        cfg.zetaris_api_key, cfg.meterless_runtime_token = "test-key", "test-token"
    cfg.memory_dir = tmp_path / ("memory-sample" if sample else "memory-live")
    cfg.logs_dir = tmp_path / "logs"
    orch = Orchestrator(cfg)
    if not sample:
        local = LocalDataLayer(cfg.data_dir)
        orch._data_layer = lambda s: local          # the same data Zetaris serves, without the network
        orch._model = lambda s: model               # the fake lane instead of Nightshift
    return orch


def _run(orch: Orchestrator, run_id: str, query: str, sample: bool):
    return orch.run(RunRequest(run_id=run_id, input={"query": query}, options={"sample_mode": sample}))


def _trace(orch: Orchestrator, run_id: str) -> list[dict]:
    return [json.loads(l) for l in (orch.cfg.logs_dir / f"trace-{run_id}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def _stats(r) -> dict:
    return next(a for a in r.output.artifacts if a["type"] == "run_stats")


def _claims_hit(text: str, claims) -> list[str]:
    return [why for pattern, why in claims if re.search(pattern, " ".join(text.split()), flags=re.IGNORECASE | re.DOTALL)]


# --- the claim guard itself ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Across the three councils, 233 supplier pairs are confirmed as shared.",
    "233 pairs are confirmed, representing GBP 34.9m.",
    "These confirmed shared suppliers include Surrey County Council.",
    "The pairs have been verified as duplicates.",
])
def test_human_only_claims_catch_overclaims(text: str) -> None:
    assert _claims_hit(text, HUMAN_ONLY_CLAIMS)


@pytest.mark.parametrize("text", [
    "228 supplier pairs are shared; 217 pairs are awaiting a human decision.",
    "A further 205 pairs require human confirmation before they can be treated as the same supplier.",
    "The match judge suggests 5 of them are the same organisation; a human decides.",
    "1 of them is resolved from a remembered human decision (mem-1).",
])
def test_human_only_claims_allow_honest_wording(text: str) -> None:
    assert not _claims_hit(text, HUMAN_ONLY_CLAIMS)


@pytest.mark.parametrize("text, hit", [
    ("4 of 8 residents would be treated differently on day one.", True),
    ("Claimants with savings above GBP 6,000 lose support in Guildford.", True),
    ("4 of 8 SYNTHETIC test residents would be treated differently on day one.", False),
    ("The capital limit differs: GBP 10,000 in Woking and GBP 6,000 in Guildford.", False),
])
def test_synthetic_label_claim(text: str, hit: bool) -> None:
    assert bool(_claims_hit(text, SYNTHETIC_LABEL_CLAIM)) is hit


# --- the supplier overlap flow in live mode ----------------------------------------------

def test_judge_opinions_never_move_pairs_and_critic_bounces_the_overclaim(tmp_path: Path) -> None:
    sample = _run(_orch(tmp_path, None, sample=True), "s-01", OVERLAP_Q, sample=True)
    assert sample.status == "success"
    s_stats = _stats(sample)

    model = FakeNemotron(
        first_draft="Across the three legacy councils, the supplier pairs are confirmed as shared duplicates.",
        second_draft="The shared pairs come from identical names; the remaining pairs are awaiting a human decision.",
    )
    orch = _orch(tmp_path, model, sample=False)
    live = _run(orch, "l-01", OVERLAP_Q, sample=False)
    assert live.status == "success", getattr(live, "error", None)
    l_stats = _stats(live)

    # the judge ran on the band ...
    assert model.judge_calls == 12
    assert l_stats["judge_hints"]["reviewed"] == 12
    assert l_stats["judge_hints"]["same"] == 6 and l_stats["judge_hints"]["different"] == 6
    # ... and moved nothing: the piles are the same size as in SAMPLE_MODE
    assert l_stats["presented"] == s_stats["presented"]
    assert l_stats["needs_human"] == s_stats["needs_human"]
    presented = next(a for a in live.output.artifacts if a.get("title", "").startswith("Shared suppliers"))
    assert all(r["status"] in ("auto", "confirmed") for r in presented["rows"])
    queue = next(a for a in live.output.artifacts if a.get("title", "").startswith("Candidates needing a human decision"))
    assert queue["judge_suggests_same"] == 6
    hinted = [r for r in queue["rows"] if r["model_verdict"]]
    assert hinted and all(r["status"] in ("needs-human", "pending") for r in hinted)
    assert [r["model_verdict"] for r in queue["rows"][:6]] == ["SAME"] * 6     # likely-same first in the human queue

    # the Critic rejected the overclaiming draft and the retry prompt said why
    events = _trace(orch, "l-01")
    rejected = [e for e in events if e["agent_name"] == "Critic" and e["action"] == "critique_draft" and e["status"] == "rejected"]
    assert rejected and "claim not supported" in rejected[0]["output_summary"]
    assert any("rejected by the Critic" in p and "only a human can confirm" in p for p in model.draft_prompts)
    assert live.output.summary == model.second_draft
    assert not _claims_hit(live.output.summary, HUMAN_ONLY_CLAIMS)
    assert l_stats["critic_bounces"] >= 2    # one for the matches, one for the draft
    judge_events = [e for e in events if e["action"] == "judge_matches"]
    assert len(judge_events) == 12 and all(e["details"]["model_verdict"] in ("SAME", "DIFFERENT") and e["details"]["receipt_id"] for e in judge_events)
    assert all("status unchanged" in e["output_summary"] for e in judge_events)
    assert any("hint for the human, not a confirmation" in e["output_summary"] for e in events if e["action"] == "critique_matches")


def test_a_model_that_keeps_overclaiming_is_replaced_by_the_template(tmp_path: Path) -> None:
    bad = "The pairs are confirmed as duplicates."
    model = FakeNemotron(first_draft=bad, second_draft=bad)
    orch = _orch(tmp_path, model, sample=False)
    live = _run(orch, "l-02", OVERLAP_Q, sample=False)
    assert live.status == "success", getattr(live, "error", None)
    briefing = next(a for a in live.output.artifacts if a["type"] == "generated_text")
    assert briefing["model"] == "template-fallback" and briefing["mode"] == "fallback"
    assert "shared (identical names after normalisation, or confirmed by a human)" in live.output.summary
    assert not _claims_hit(live.output.summary, HUMAN_ONLY_CLAIMS)
    assert any(e["status"] == "fallback" and e["model"] == "template-fallback" for e in _trace(orch, "l-02"))


# --- the policy gap flow in live mode -----------------------------------------------------

def test_policy_note_must_keep_the_synthetic_label(tmp_path: Path) -> None:
    model = FakeNemotron(
        first_draft="Of 9 clauses, 4 differ. 4 of 8 residents would be treated differently on day one.",
        second_draft="Of 9 clauses, 4 differ. 4 of 8 SYNTHETIC test residents would be treated differently on day one.",
    )
    orch = _orch(tmp_path, model, sample=False)
    live = _run(orch, "l-03", POLICY_Q, sample=False)
    assert live.status == "success", getattr(live, "error", None)
    held = next(a for a in live.output.artifacts if a["type"] == "draft")["draft"]
    assert "SYNTHETIC" in held["text"]
    events = _trace(orch, "l-03")
    assert any(e["action"] == "critique_draft" and e["status"] == "rejected" and "SYNTHETIC" in e["output_summary"] for e in events)
