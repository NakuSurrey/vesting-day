"""PlannerAgent: decides which checks a broad question needs, delegates them, assesses what came
back, and revises the plan.

A question like "What are the biggest risks on vesting day?" has no single flow. The Planner
chooses the steps. In live mode NVIDIA Nemotron (through Nightshift) proposes the plan as JSON
and this code validates it against the checks that exist - the model decides, the code keeps
it safe. In SAMPLE_MODE a rule-based planner, badged as such, picks the checks the question's
words point at. After each step the Planner assesses the result: it broadens a step that
cannot run as asked (one council named for a two-council check), records a widened window,
and carries on without a step that failed, saying so. Every decision is a trace line.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.adapters.nightshift import ModelError
from app.agents.base import Agent
from app.agents.router import window_days_in

COUNCILS = ("Woking", "Guildford", "Waverley")

CHECKS: dict[str, dict[str, Any]] = {
    "contract_cliff": {
        "agent": "Researcher",
        "what": "contracts ending around vesting day with no extension date recorded past it, per council, "
                "and a novation letter drafted for the largest (held for approval)",
        "params": {"window_days": "days either side of vesting day, default 180"},
    },
    "supplier_overlap": {
        "agent": "Researcher",
        "what": "suppliers two or more councils both pay, with spend; similar names queued for a human decision; "
                "remembered human decisions applied",
        "params": {},
    },
    "policy_gap": {
        "agent": "Researcher",
        "what": "Council Tax Support clauses that differ between Woking and Guildford, each citing a page of the "
                "published scheme, and the day-one effect on SYNTHETIC test residents (options note held for approval)",
        "params": {},
    },
}
URGENCY = ["contract_cliff", "supplier_overlap", "policy_gap"]   # the default order: dated deadlines first

# words that ask for the whole picture: every check runs, whatever else the question names
WHOLE_WORDS = ["brief", "overview", "everything", "summar", "merger", "readiness", "big picture", "state of play", "transition",
               "integration", "day one", "day-one", "vesting day", "what happens", "what changes", "where do i start", "where to start"]
# words that name one area: only those checks run (a question can name more than one)
DOMAIN_WORDS = {
    "supplier_overlap": ["supplier", "vendor", "payee", "spend", "paid", "pay ", "duplicate", "consolidat", "firm", "compan"],
    "contract_cliff": ["contract", "novat", "expir", "renew", "register", "deal", "agreement", "cliff", "end date"],
    "policy_gap": ["council tax", "cts", "ctr", "policy", "policies", "scheme", "resident", "claimant", "benefit", "harmonis", "harmoniz"],
}

PLAN_SYSTEM = (
    "You plan the work of a small team of agents for the finance lead of England's merging West Surrey councils "
    "(Woking, Guildford and Waverley become one authority on vesting day, 1 April 2027). You may only choose from the "
    "checks listed in the message. Reply with JSON only, no prose and no code fences, in exactly this shape: "
    '{"focus": "<one line: what the question is really asking>", "steps": [{"check": "<check name>", '
    '"why": "<one line>", "window_days": <integer, contract_cliff only>}]}. '
    "Choose the fewest checks that answer the question, 1 to 3 steps, ordered by urgency for the finance lead."
)


@dataclass
class Step:
    check: str
    params: dict[str, Any] = field(default_factory=dict)
    why: str = ""


@dataclass
class Plan:
    steps: list[Step]
    source: str                      # "model" or "rules"
    focus: str = ""
    model: Optional[str] = None
    receipt_id: Optional[str] = None
    note: str = ""                   # why the rules were used when a model was available


class PlannerAgent(Agent):
    name = "Planner"
    role = "Decides which checks a broad question needs (NVIDIA Nemotron proposes the plan in live mode; rules in sample mode), delegates them, assesses each result and revises the plan"

    # --- planning --------------------------------------------------------------

    def plan(self, question: str, councils: list[str]) -> Plan:
        if self.ctx.sample_mode:
            plan = self._rules_plan(question, councils)
            plan.model = "sample-mode/planner-rules"
            self.trace("plan", question, self._describe(plan), target_agent=CHECKS[plan.steps[0].check]["agent"],
                       model=plan.model, confidence=0.8, steps=[s.check for s in plan.steps], source=plan.source)
            return plan
        prompt = self._prompt(question, councils)
        try:
            out = self.ctx.model.complete(PLAN_SYSTEM, prompt, max_tokens=400)
        except ModelError as e:
            plan = self._rules_plan(question, councils)
            plan.note = f"model error: {e}"
            self.trace("plan", question, f"model unavailable ({e}); rule-based plan instead: {self._describe(plan)}",
                       target_agent=CHECKS[plan.steps[0].check]["agent"], model=self.ctx.model.badge, status="fallback",
                       confidence=0.7, steps=[s.check for s in plan.steps], source=plan.source)
            return plan
        plan, problems = self._validate(out.text, question)
        if plan is None:
            plan = self._rules_plan(question, councils)
            plan.note = "model plan rejected: " + "; ".join(problems)
            self.trace("plan", question, f"model plan rejected ({'; '.join(problems)}); rule-based plan instead: {self._describe(plan)}",
                       target_agent=CHECKS[plan.steps[0].check]["agent"], model=out.model, status="fallback", confidence=0.7,
                       receipt_id=out.receipt_id, steps=[s.check for s in plan.steps], source=plan.source, model_text=out.text[:300])
            return plan
        plan.model, plan.receipt_id = out.model, out.receipt_id
        self.trace("plan", question, self._describe(plan), target_agent=CHECKS[plan.steps[0].check]["agent"],
                   model=out.model, confidence=0.85, receipt_id=out.receipt_id, provider=out.provider, usage=out.usage,
                   steps=[s.check for s in plan.steps], source=plan.source)
        return plan

    def _prompt(self, question: str, councils: list[str]) -> str:
        lines = [f"QUESTION: {question}", f"COUNCILS NAMED: {', '.join(councils) if councils else 'none (all three)'}",
                 f"DEFAULT CONTRACT WINDOW: {self.ctx.settings.cliff_window_days} days either side of vesting day", "", "CHECKS YOU MAY USE:"]
        for name, spec in CHECKS.items():
            lines.append(f"- {name}: {spec['what']}" + (f" (params: {spec['params']})" if spec["params"] else ""))
        lines.append("")
        lines.append("Reply with the JSON object only.")
        return "\n".join(lines)

    def _validate(self, text: str, question: str) -> tuple[Optional[Plan], list[str]]:
        """Accept only a plan made of the checks that exist, 1-3 steps, sane windows. Anything else is rejected."""
        problems: list[str] = []
        raw = text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return None, ["no JSON object in the model's reply"]
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return None, [f"invalid JSON: {e.msg}"]
        steps_in = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(steps_in, list) or not steps_in:
            return None, ["'steps' missing or empty"]
        steps: list[Step] = []
        seen: set[str] = set()
        for s in steps_in[:6]:
            if not isinstance(s, dict):
                problems.append("a step is not an object"); continue
            check = str(s.get("check", "")).strip()
            if check not in CHECKS:
                problems.append(f"unknown check '{check[:40]}'"); continue
            if check in seen:
                continue
            seen.add(check)
            params: dict[str, Any] = {}
            if check == "contract_cliff":
                w = s.get("window_days", None)
                try:
                    w = int(w) if w is not None else None
                except (TypeError, ValueError):
                    w = None
                if w is None:
                    w = window_days_in(question) or self.ctx.settings.cliff_window_days
                params["window_days"] = max(14, min(int(w), 730))
            steps.append(Step(check=check, params=params, why=str(s.get("why", ""))[:200]))
        if not steps:
            return None, problems or ["no usable steps"]
        if len(steps) > 3:
            steps = steps[:3]
        return Plan(steps=steps, source="model", focus=str(data.get("focus", ""))[:200]), problems

    def _rules_plan(self, question: str, councils: list[str]) -> Plan:
        q = question.lower()
        whole = any(w in q for w in WHOLE_WORDS)
        hit = [c for c in URGENCY if any(w in q for w in DOMAIN_WORDS[c])]
        checks = URGENCY if (whole or not hit) else hit
        why = "the question asks for the whole picture" if (whole or not hit) else "the question names this area"
        steps = []
        for c in checks:
            params = {"window_days": window_days_in(question) or self.ctx.settings.cliff_window_days} if c == "contract_cliff" else {}
            steps.append(Step(check=c, params=params, why=why))
        focus = ("a day-one brief across contracts, suppliers and Council Tax Support" if checks == URGENCY
                 else "the areas the question names: " + ", ".join(checks))
        return Plan(steps=steps, source="rules", focus=focus)

    @staticmethod
    def _describe(plan: Plan) -> str:
        parts = [s.check + (f" (window {s.params['window_days']} days)" if s.params.get("window_days") else "") for s in plan.steps]
        return f"{len(plan.steps)} step(s) from {plan.source}: {' -> '.join(parts)}" + (f"; focus: {plan.focus}" if plan.focus else "")

    # --- delegation and assessment ----------------------------------------------

    def delegate(self, step: Step, councils: list[str], index: int, total: int) -> None:
        self.trace("delegate", f"step {index} of {total}: {step.check} for {', '.join(councils)}",
                   f"handing to the {step.check.replace('_', ' ')} agents" + (f" ({step.why})" if step.why else ""),
                   target_agent=CHECKS[step.check]["agent"], confidence=1.0, step=step.check, params=step.params)

    def revise(self, step: Step, reason: str, councils_before: list[str], councils_after: list[str]) -> dict[str, Any]:
        rev = {"step": step.check, "reason": reason, "councils_before": councils_before, "councils_after": councils_after}
        self.trace("revise_plan", f"{step.check} for {', '.join(councils_before) or 'none'}",
                   f"{reason}; running it for {', '.join(councils_after)}", target_agent=CHECKS[step.check]["agent"],
                   status="needs_revision", confidence=1.0, retry_count=1, **rev)
        return rev

    def assess(self, step: Step, result: dict[str, Any]) -> str:
        stats = next((a for a in result.get("artifacts", []) if a.get("type") == "run_stats"), {}) or {}
        held = [a["draft"]["id"] for a in result.get("artifacts", []) if a.get("type") == "draft" and a.get("draft")]
        if step.check == "contract_cliff":
            total = stats.get("total_hard_cliff_gbp")
            n = sum(v.get("contracts", 0) for v in (stats.get("per_council") or {}).values())
            note = (f"{n} contracts end within {stats.get('window_days', '?')} days of vesting day with no extension date recorded past it"
                    + (f", stated value GBP {total:,.0f}" if isinstance(total, (int, float)) else "")
                    + (f"; {stats['shared_suppliers_on_cliff']} of those suppliers are also paid by another council" if stats.get("shared_suppliers_on_cliff") else ""))
            if stats.get("widened_to"):
                note += f"; no contract ended within the {stats.get('asked_window_days')} days asked, so the Researcher widened the window to {stats['widened_to']} days"
        elif step.check == "supplier_overlap":
            spend = stats.get("shared_spend_gbp")
            note = (f"{stats.get('presented', 0)} supplier pairs shared" + (f", GBP {spend:,.0f} combined spend" if isinstance(spend, (int, float)) else "")
                    + f"; {stats.get('needs_human', 0)} similar-name pairs awaiting a human decision")
            hints = stats.get("judge_hints") or {}
            if hints.get("reviewed"):
                note += f" (the match judge suggests {hints.get('same', 0)} same and {hints.get('different', 0)} different; a person decides)"
            recalled = [a for a in result.get("artifacts", []) if a.get("type") == "memory" and a.get("decisions")]
            if recalled and recalled[0]["decisions"]:
                ids = sorted({d["memory_id"] for d in recalled[0]["decisions"].values()})
                note += f"; {len(ids)} pair(s) resolved using remembered human decision(s) {', '.join(ids)}"
        else:
            grid = next((a for a in result.get("artifacts", []) if a.get("type") == "clause_grid"), None)
            if grid:
                n_diff, n_same = len(grid.get("differences", [])), len(grid.get("agreements", []))
                note = f"{n_diff} of {n_diff + n_same} Council Tax Support clauses differ"
                table = next((a for a in result.get("artifacts", []) if a.get("type") == "table" and a.get("synthetic")), None)
                if table and table.get("rows"):
                    affected = sum(1 for r in table["rows"] if r.get("differs_between_councils"))
                    note += f"; {affected} of {len(table['rows'])} SYNTHETIC test residents would be treated differently on day one"
            else:
                note = "no clause table for these councils"
        if held:
            note += f"; held for approval: {', '.join(held)}"
        self.trace("assess", f"{step.check} result", note + "; accepted into the brief", target_agent="Writer", confidence=1.0, step=step.check)
        return note

    def skip(self, step: Step, error: Exception) -> str:
        note = f"{step.check} could not run ({type(error).__name__}: {str(error)[:120]}); continuing with the remaining checks and saying so in the brief"
        self.trace("assess", f"{step.check} result", note, target_agent="Writer", status="error", confidence=1.0, step=step.check)
        return note
