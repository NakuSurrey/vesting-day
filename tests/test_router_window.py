"""The contract-cliff window comes from the user's own words, not a fixed default.

A fresh-clone check asked "Which Guildford contracts end within a year of vesting day?" and got a
+/-180-day answer: the old parser only read digits followed by days or months.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.router import window_days_in
from app.config import Settings
from app.orchestrator import Orchestrator
from app.schemas import RunRequest


@pytest.mark.parametrize("q, days", [
    ("Which contracts end within six months of vesting day?", 180),
    ("Which contracts end within 6 months of vesting day?", 180),
    ("Which contracts end within three months of vesting day?", 90),
    ("Which Guildford contracts end within a year of vesting day?", 365),
    ("contracts ending within 1 year of vesting day", 365),
    ("contracts ending within 2 years of vesting day", 730),
    ("Which contracts expire within 18 months of vesting day?", 540),
    ("Which contracts end within 90 days of vesting day?", 90),
    ("Which contracts end within two weeks of vesting day?", 14),
    ("Which contracts end within half a year of vesting day?", 180),
    ("Show me the 12-month contract cliff", 360),
])
def test_window_days_in(q: str, days: int) -> None:
    assert window_days_in(q) == days


@pytest.mark.parametrize("q", [
    "Which contracts end around vesting day?",
    "Which contracts need novation on vesting day?",       # 'vesting day' is not a window
    "What changes on day one for residents?",
])
def test_no_window_named(q: str) -> None:
    assert window_days_in(q) is None


def _orch(tmp_path: Path) -> Orchestrator:
    cfg = Settings()
    cfg.sample_mode = True
    cfg.memory_dir = tmp_path / "memory"
    cfg.logs_dir = tmp_path / "logs"
    return Orchestrator(cfg)


def test_a_year_window_changes_the_answer(tmp_path: Path) -> None:
    orch = _orch(tmp_path)
    year = orch.run(RunRequest(run_id="w-year", input={"query": "Which Guildford contracts end within a year of vesting day?"}, options={"sample_mode": True}))
    half = orch.run(RunRequest(run_id="w-half", input={"query": "Which Guildford contracts end within six months of vesting day?"}, options={"sample_mode": True}))
    assert year.status == "success" and half.status == "success"
    assert "plus or minus 365 days" in year.output.summary
    assert "plus or minus 180 days" in half.output.summary
    count = lambda r: next(a for a in r.output.artifacts if a.get("title", "").startswith("Hard cliff"))["count"]
    assert count(year) >= count(half)     # a wider window can only add contracts


# --- people's own phrasings route to the right flow; off-topic stays an honest "unsupported" ------

def _flow(orch: Orchestrator, run_id: str, q: str) -> str:
    import json
    r = orch.run(RunRequest(run_id=run_id, input={"query": q}, options={"sample_mode": True}))
    ev = [json.loads(l) for l in (orch.cfg.logs_dir / f"trace-{run_id}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    c = next(e for e in ev if e["agent_name"] == "Router")
    if r.status != "success":
        return "unsupported"
    return c["output_summary"].split("flow=", 1)[1].split()[0]


@pytest.mark.parametrize("q, flow", [
    ("What suppliers do Woking and Guildford both pay?", "supplier_overlap"),
    ("Which companies are paid by all three councils?", "supplier_overlap"),
    ("Do Guildford and Waverley use the same firms?", "supplier_overlap"),
    ("Which payees are common to Woking and Waverley?", "supplier_overlap"),
    ("Which contracts expire around April 2027?", "contract_cliff"),
    ("What deals end in the first quarter after the merger?", "contract_cliff"),
    ("Which Waverley contracts run out soon after vesting day?", "contract_cliff"),
    ("Which council has the more generous council tax reduction scheme?", "policy_gap"),
    ("What happens on day one to a resident with 8000 pounds of savings?", "policy_gap"),
    ("Is 'Unit 4 Business Software Ltd' (Waverley) the same company as 'Unit4 Business Software Ltd' (Guildford)? Confirm.", "confirm_match"),
    ("What is the weather in Woking?", "unsupported"),
    ("Summarise the merger risks", "day_one_brief"),
    ("What are the biggest risks on vesting day?", "day_one_brief"),
    ("Give me a day-one brief for the merger", "day_one_brief"),
    ("What should the finance lead do first?", "day_one_brief"),
    ("What happens on vesting day?", "day_one_brief"),
    ("Which contracts are at risk around vesting day?", "contract_cliff"),
    ("Tell me a joke about councils", "unsupported"),
])
def test_judge_phrasings_route(tmp_path: Path, q: str, flow: str) -> None:
    assert _flow(_orch(tmp_path), "rq", q) == flow


def test_first_quarter_window() -> None:
    assert window_days_in("What deals end in the first quarter after the merger?") == 90
