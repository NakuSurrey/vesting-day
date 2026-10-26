"""The Planner: a broad question is answered by planning, delegating, assessing and revising.

Live mode: the model proposes the plan as JSON and the code validates it (unknown checks dropped,
garbage rejected, rules used instead and the trace says so). Sample mode: a rule-based planner,
badged as such. A step that cannot run as asked is revised; a step that fails is skipped and the
brief says so; if every step fails the run returns a structured error. The contract flow widens
an empty window on the Critic's request. All of it is in the trace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.datalayer import DataLayerError, LocalDataLayer
from app.adapters.nightshift import Completion, ModelClient
from app.agents.planner import PLAN_SYSTEM
from app.agents.resolver import JUDGE_SYSTEM
from app.config import Settings
from app.orchestrator import Orchestrator
from app.schemas import RunRequest

RISKS_Q = "Summarise the merger risks"


class FakeLive(ModelClient):
    """Answers the plan prompt with `plan_text`, judge prompts with SAME/DIFFERENT, drafts with `draft_text`."""

    badge = "fake/nemotron"

    def __init__(self, plan_text: str, draft_text: str = "") -> None:
        self.plan_text, self.draft_text = plan_text, draft_text
        self.calls: list[str] = []

    def complete(self, system: str, user: str, max_tokens: int = 768, temperature: float = 0.1) -> Completion:
        if system == PLAN_SYSTEM:
            self.calls.append("plan")
            text = self.plan_text
        elif system == JUDGE_SYSTEM:
            self.calls.append("judge")
            text = "SAME" if len(self.calls) % 2 else "DIFFERENT"
        else:
            self.calls.append("draft")
            text = self.draft_text or user.split("EVIDENCE:", 1)[-1][:600]
        return Completion(text=text, model=self.badge, receipt_id=f"rcpt_fake_{len(self.calls)}", provider="fake", usage={})


class FailingContracts(LocalDataLayer):
    """A data layer whose contract queries fail, as a live Zetaris might for one source."""

    def run_sql(self, sql: str, limit: int = 5000):
        if "{contracts}" in sql or "contracts" in sql.lower().split("from", 1)[-1][:40]:
            raise DataLayerError("Zetaris did not respond after 3 retries (contracts)", recoverable=True, type_="UpstreamTimeout")
        return super().run_sql(sql, limit=limit)


class FailingEverything(LocalDataLayer):
    def run_sql(self, sql: str, limit: int = 5000):
        raise DataLayerError("Zetaris did not respond after 3 retries", recoverable=True, type_="UpstreamTimeout")


class EmptyNarrowWindow(LocalDataLayer):
    """Returns no contracts for windows narrower than 60 days, so the widening loop has to run."""

    def run_sql(self, sql: str, limit: int = 5000):
        rows = super().run_sql(sql, limit=limit)
        if "end_date >= '" in sql and "end_date <= '" in sql:
            lo = sql.split("end_date >= '", 1)[1][:10]
            hi = sql.split("end_date <= '", 1)[1][:10]
            from datetime import date
            if (date.fromisoformat(hi) - date.fromisoformat(lo)).days < 120:
                return []
        return rows


def _orch(tmp_path: Path, sample: bool, model: ModelClient | None = None, data: LocalDataLayer | None = None) -> Orchestrator:
    cfg = Settings()
    cfg.sample_mode = sample
    cfg.companies_house_api_key = ""
    if not sample:
        cfg.zetaris_api_key, cfg.meterless_runtime_token = "test-key", "test-token"
    cfg.memory_dir = tmp_path / "memory"
    cfg.logs_dir = tmp_path / "logs"
    orch = Orchestrator(cfg)
    local = data or LocalDataLayer(cfg.data_dir)
    orch._data_layer = lambda s: local
    if model is not None:
        orch._model = lambda s: model
    return orch


def _run(orch: Orchestrator, run_id: str, q: str):
    return orch.run(RunRequest(run_id=run_id, input={"query": q}, options={"sample_mode": orch.cfg.sample_mode}))


def _trace(orch: Orchestrator, run_id: str) -> list[dict]:
    return [json.loads(l) for l in (orch.cfg.logs_dir / f"trace-{run_id}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def _art(r, kind: str) -> dict:
    return next(a for a in r.output.artifacts if a["type"] == kind)


# --- sample mode: rules plan, delegation, assessment, revision ---------------------------------

def test_broad_question_is_planned_delegated_and_assessed(tmp_path: Path) -> None:
    orch = _orch(tmp_path, sample=True)
    r = _run(orch, "b-01", RISKS_Q)
    assert r.status == "success", getattr(r, "error", None)
    plan, stats = _art(r, "plan"), _art(r, "run_stats")
    assert plan["source"] == "rules" and [s["check"] for s in plan["steps"]] == ["contract_cliff", "supplier_overlap", "policy_gap"]
    assert stats["steps_run"] == 3 and stats["steps_failed"] == 0
    assert set(stats["drafts_held"]) == {"draft-1", "draft-2"}
    ev = _trace(orch, "b-01")
    planner = [e for e in ev if e["agent_name"] == "Planner"]
    assert [e["action"] for e in planner] == ["plan", "delegate", "assess", "delegate", "assess", "delegate", "assess"]
    assert planner[0]["model"] == "sample-mode/planner-rules"
    assert {e["target_agent"] for e in planner if e["action"] == "delegate"} == {"Researcher"}
    assert {a.name for a in r.agents} >= {"Router", "Planner", "Researcher", "Resolver", "Memory", "Critic", "Writer", "ApprovalGate"}
    s = r.output.summary
    assert "173 contracts" in s and "228 supplier pairs shared" in s and "4 of 9" in s and "SYNTHETIC" in s
    assert "draft-1" in s and "draft-2" in s and "nothing sent" in s
    assert _art(r, "generated_text")["model"] == "sample-mode/template"   # the Critic accepts the evidence-only brief as written
    assert stats["critic_bounces"] == 1                                   # only the overlap step's planned bounce


def test_planner_runs_only_the_area_the_question_names(tmp_path: Path) -> None:
    r = _run(_orch(tmp_path, sample=True), "b-02", "What are the supplier risks?")
    assert r.status == "success"
    assert [s["check"] for s in _art(r, "plan")["steps"]] == ["supplier_overlap"]
    assert _art(r, "run_stats")["drafts_held"] == []


def test_planner_revises_steps_that_cannot_run_as_asked(tmp_path: Path) -> None:
    orch = _orch(tmp_path, sample=True)
    r = _run(orch, "b-03", "What are Waverley's risks on vesting day?")
    assert r.status == "success"
    plan = _art(r, "plan")
    reasons = [rev["reason"] for rev in plan["revisions"]]
    assert any("at least two councils" in x for x in reasons) and any("Woking and Guildford" in x for x in reasons)
    ev = _trace(orch, "b-03")
    revs = [e for e in ev if e["action"] == "revise_plan"]
    assert len(revs) == 2 and all(e["status"] == "needs_revision" and e["retry_count"] == 1 for e in revs)
    steps = _art(r, "step_results")["steps"]
    assert next(s for s in steps if s["check"] == "contract_cliff")["councils"] == ["Waverley"]
    assert next(s for s in steps if s["check"] == "supplier_overlap")["councils"] == ["Woking", "Guildford", "Waverley"]
    assert "Plan revised" in r.output.summary and "66 contracts" in r.output.summary


# --- live mode: the model proposes the plan, the code validates it -----------------------------

def test_model_plan_is_used_when_valid(tmp_path: Path) -> None:
    model = FakeLive('{"focus": "contract exposure only", "steps": [{"check": "contract_cliff", "why": "dated deadlines first", "window_days": 90}]}')
    orch = _orch(tmp_path, sample=False, model=model)
    r = _run(orch, "l-01", "What should the finance lead worry about?")
    assert r.status == "success", getattr(r, "error", None)
    plan = _art(r, "plan")
    assert plan["source"] == "model" and plan["model"] == "fake/nemotron" and plan["receipt_id"]
    assert [s["check"] for s in plan["steps"]] == ["contract_cliff"] and plan["steps"][0]["params"]["window_days"] == 90
    ev = _trace(orch, "l-01")
    p = next(e for e in ev if e["agent_name"] == "Planner" and e["action"] == "plan")
    assert p["status"] == "success" and p["model"] == "fake/nemotron" and p["details"]["receipt_id"] and p["details"]["source"] == "model"
    cliff = next(s for s in _art(r, "step_results")["steps"] if s["check"] == "contract_cliff")
    assert "plus or minus 90 days" in cliff["summary"]
    assert model.calls[0] == "plan"


def test_invalid_model_plan_falls_back_to_rules_and_says_so(tmp_path: Path) -> None:
    model = FakeLive("Sure! I would start by looking at the contracts and then the suppliers.")
    orch = _orch(tmp_path, sample=False, model=model)
    r = _run(orch, "l-02", RISKS_Q)
    assert r.status == "success", getattr(r, "error", None)
    plan = _art(r, "plan")
    assert plan["source"] == "rules" and "rejected" in plan["note"]
    p = next(e for e in _trace(orch, "l-02") if e["agent_name"] == "Planner" and e["action"] == "plan")
    assert p["status"] == "fallback" and "rule-based plan instead" in p["output_summary"]


def test_unknown_checks_in_a_model_plan_are_dropped(tmp_path: Path) -> None:
    model = FakeLive('```json\n{"steps": [{"check": "email_the_suppliers"}, {"check": "policy_gap", "why": "residents"}, {"check": "drop_table"}]}\n```')
    r = _run(_orch(tmp_path, sample=False, model=model), "l-03", "What changes for residents?")
    assert r.status == "success", getattr(r, "error", None)
    plan = _art(r, "plan")
    assert plan["source"] == "model" and [s["check"] for s in plan["steps"]] == ["policy_gap"]


# --- failure handling: a failed step is skipped and named; all failing is a structured error ---

def test_a_failed_step_is_skipped_and_the_brief_says_so(tmp_path: Path) -> None:
    cfg_data = FailingContracts(Settings().data_dir)
    orch = _orch(tmp_path, sample=True, data=cfg_data)
    r = _run(orch, "f-01", RISKS_Q)
    assert r.status == "success", getattr(r, "error", None)
    stats = _art(r, "run_stats")
    assert stats["steps_failed"] == 1 and stats["steps_run"] == 2
    assert "not available this run" in r.output.summary and "228 supplier pairs shared" in r.output.summary
    ev = _trace(orch, "f-01")
    assert any(e["agent_name"] == "Planner" and e["action"] == "assess" and e["status"] == "error" and "could not run" in e["output_summary"] for e in ev)


def test_every_step_failing_returns_a_structured_error(tmp_path: Path) -> None:
    r = _run(_orch(tmp_path, sample=True, data=FailingEverything(Settings().data_dir)), "f-02", RISKS_Q)
    assert r.status == "error" and r.error.type == "UpstreamTimeout" and r.error.recoverable is True


# --- the contract flow widens an empty window on the Critic's request --------------------------

def test_empty_window_is_widened_and_labelled(tmp_path: Path) -> None:
    orch = _orch(tmp_path, sample=True, data=EmptyNarrowWindow(Settings().data_dir))
    r = _run(orch, "w-01", "Which contracts end within two weeks of vesting day?")
    assert r.status == "success", getattr(r, "error", None)
    s = r.output.summary
    assert s.startswith("No contract ends within 14 days of vesting day")
    assert "widened to 112 days" in s          # 14 -> 28 -> 56 -> 112: three widenings, then rows
    ev = _trace(orch, "w-01")
    asks = [e for e in ev if e["action"] == "critique_coverage"]
    assert len(asks) == 3 and all(e["status"] == "needs_revision" and e["target_agent"] == "Researcher" for e in asks)
    queries = [e for e in ev if e["action"] == "query_data_layer" and "contracts ending within" in e["input_summary"]]
    assert [e["retry_count"] for e in queries] == [0, 1, 2, 3]
    assert "widened query" in queries[-1]["output_summary"]
    stats = _art(r, "run_stats")
    assert stats["asked_window_days"] == 14 and stats["widened_to"] == 112


def test_normal_window_is_not_widened(tmp_path: Path) -> None:
    orch = _orch(tmp_path, sample=True)
    r = _run(orch, "w-02", "Which contracts end within six months of vesting day?")
    assert r.status == "success"
    assert not any(e["action"] == "critique_coverage" for e in _trace(orch, "w-02"))
    assert _art(r, "run_stats")["widened_to"] is None and not r.output.summary.startswith("No contract")


# --- the Critic on the brief: timing and numbers in the right place ----------------------------

TWO_STEP_PLAN = ('{"focus": "contracts and suppliers", "steps": [{"check": "contract_cliff", "why": "dated deadlines", "window_days": 180}, '
                 '{"check": "supplier_overlap", "why": "shared spend"}]}')


class BriefFake(FakeLive):
    """Like FakeLive, but the day-one brief itself is a fixed text (as Nemotron wrote it live)."""

    def __init__(self, plan_text: str, brief: str) -> None:
        super().__init__(plan_text)
        self.brief = brief

    def complete(self, system: str, user: str, max_tokens: int = 768, temperature: float = 0.1) -> Completion:
        if "Write the day-one brief now" in user:
            self.calls.append("brief")
            return Completion(text=self.brief, model=self.badge, receipt_id=f"rcpt_fake_{len(self.calls)}", provider="fake", usage={})
        return super().complete(system, user, max_tokens, temperature)


def test_brief_that_overstates_timing_or_moves_a_number_is_sent_back(tmp_path: Path) -> None:
    # the two mistakes Nemotron made in the first live run: "end on vesting day", and the cliff's 45 put under suppliers
    brief = ("Vesting day risk brief\n\n"
             "1. **Contract cliff exposure**: 173 contracts end on vesting day with no extension date recorded.\n"
             "2. **Shared supplier consolidation**: the shared pairs include 45 suppliers paid by multiple councils.\n\n"
             "Held for approval: draft-1.")
    orch = _orch(tmp_path, sample=False, model=BriefFake(TWO_STEP_PLAN, brief))
    r = _run(orch, "c-01", RISKS_Q)
    assert r.status == "success", getattr(r, "error", None)
    ev = _trace(orch, "c-01")
    rejected = [e["output_summary"] for e in ev if e["action"] == "critique_draft" and e["status"] == "rejected"]
    assert any("not on it" in x for x in rejected)
    assert any("number 45 in priority 2" in x and "Contract" in x for x in rejected)
    text = _art(r, "generated_text")
    assert text["model"] == "template-fallback"             # rejected twice -> the evidence-only template ships
    assert "end on vesting day" not in r.output.summary and "within 180 days of vesting day" in r.output.summary


def test_brief_with_numbers_in_their_own_sections_passes(tmp_path: Path) -> None:
    brief = ("Vesting day risk brief\n\n"
             "1. **Contract cliff**: 173 contracts end within 180 days of vesting day with no extension date recorded; "
             "45 of their suppliers are also paid by another council.\n"
             "2. **Shared suppliers**: 228 supplier pairs are shared across the councils.\n\n"
             "Held for approval: draft-1.")
    orch = _orch(tmp_path, sample=False, model=BriefFake(TWO_STEP_PLAN, brief))
    r = _run(orch, "c-02", RISKS_Q)
    assert r.status == "success", getattr(r, "error", None)
    assert _art(r, "generated_text")["model"] == "fake/nemotron"
    assert r.output.summary.startswith("Vesting day risk brief")


def test_cliff_timing_rule_only_catches_on_vesting_day() -> None:
    import re
    from app.agents.critic import cliff_timing_claims
    (pattern, why), = cliff_timing_claims(180)
    hit = lambda t: re.search(pattern, t, flags=re.IGNORECASE)
    assert hit("173 contracts end on vesting day") and hit("contracts expiring on 1 April 2027") and hit("they all end at vesting day")
    assert not hit("173 contracts end within 180 days of vesting day")
    assert not hit("the largest ends on 14 April 2027, 13 days after vesting day")
    assert not hit("contracts that end on or around vesting day")
    assert "within 180 days" in why
