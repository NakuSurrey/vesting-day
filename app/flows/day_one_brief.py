"""Flow: the day-one brief - a broad question answered by planning, delegating, assessing and revising.

Router -> Planner (which checks does this question need? Nemotron proposes in live mode, rules in sample
mode) -> for each step: Planner delegates to the specialist agents (Researcher, Resolver, Memory, Critic,
Writer, ApprovalGate run their own flow), the Planner assesses what came back and revises the plan when a
step cannot run as asked -> Writer (one prioritised brief from the checks' evidence) -> Critic (numbers and
claims) -> output. Drafted actions from the checks stay held for approval; nothing is sent.
"""

from __future__ import annotations

from typing import Any, Callable

from app.adapters.datalayer import DataLayerError
from app.adapters.nightshift import ModelError
from app.agents.base import RunContext
from app.agents.critic import HUMAN_ONLY_CLAIMS, SYNTHETIC_LABEL_CLAIM, CriticAgent, cliff_timing_claims, must_name_claims
from app.agents.planner import COUNCILS, PlannerAgent, Step
from app.agents.writer import WriterAgent
from app.flows import contract_cliff, policy_gap, supplier_overlap
from app.flows.common import checked_draft, numbers_in

RUNNERS: dict[str, Callable[[RunContext, dict[str, Any]], dict[str, Any]]] = {
    "contract_cliff": contract_cliff.run,
    "supplier_overlap": supplier_overlap.run,
    "policy_gap": policy_gap.run,
}
HEADINGS = {"contract_cliff": "Contracts", "supplier_overlap": "Suppliers", "policy_gap": "Council Tax Support"}


def run(ctx: RunContext, sources: dict[str, Any]) -> dict[str, Any]:
    asked_councils = list(ctx.councils) if ctx.councils and ctx.councils != list(COUNCILS) else []
    planner = PlannerAgent(ctx)
    critic = CriticAgent(ctx)
    writer = WriterAgent(ctx)

    plan = planner.plan(ctx.query, asked_councils)
    base_councils, base_params = list(ctx.councils), dict(ctx.params)
    step_results: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    failures: list[Exception] = []
    drafts_held: list[dict[str, Any]] = []
    recalled_ids: list[str] = []
    bounces = 0

    for i, step in enumerate(plan.steps, start=1):
        councils = asked_councils or list(COUNCILS)
        # the Planner revises a step that cannot run as asked, and says why
        if step.check == "supplier_overlap" and len(councils) < 2:
            revisions.append(planner.revise(step, "supplier overlap needs at least two councils; broadening to all three", councils, list(COUNCILS)))
            councils = list(COUNCILS)
        if step.check == "policy_gap":
            if not {"Woking", "Guildford"} <= set(councils):
                revisions.append(planner.revise(step, "the Council Tax Support clause table covers Woking and Guildford (Waverley's scheme is not loaded yet); comparing those two", councils, ["Woking", "Guildford"]))
            councils = ["Woking", "Guildford"]      # the clause table covers these two; the flow compares them
        planner.delegate(step, councils, i, len(plan.steps))
        ctx.councils, ctx.params = councils, {**base_params, **step.params}
        try:
            result = RUNNERS[step.check](ctx, sources)
        except (DataLayerError, ModelError) as e:
            failures.append(e)
            step_results.append({"check": step.check, "heading": HEADINGS[step.check], "councils": councils, "status": "failed",
                                 "note": planner.skip(step, e), "summary": "", "artifacts": []})
            continue
        finally:
            ctx.councils, ctx.params = base_councils, base_params
        note = planner.assess(step, result)
        arts = [a for a in result.get("artifacts", []) if a.get("type") != "run_mode"]
        stats = next((a for a in arts if a.get("type") == "run_stats"), {}) or {}
        bounces += int(stats.get("critic_bounces") or 0)
        for a in arts:
            if a.get("type") == "draft" and a.get("draft"):
                drafts_held.append({"id": a["draft"]["id"], "title": a["draft"]["title"], "kind": a["draft"]["kind"], "status": a["draft"]["status"], "from": step.check})
            if a.get("type") == "memory" and a.get("decisions"):
                recalled_ids += [d["memory_id"] for d in a["decisions"].values()]
        step_results.append({"check": step.check, "heading": HEADINGS[step.check], "councils": councils, "params": step.params, "status": "done",
                             "note": note, "summary": result["summary"], "recommendations": result.get("recommendations", []), "artifacts": arts})

    done = [s for s in step_results if s["status"] == "done"]
    if not done:
        raise failures[0]
    recalled_ids = sorted(set(recalled_ids))

    evidence = [f"question: {ctx.query}", f"plan: {len(plan.steps)} checks chosen by {plan.source}" + (f"; focus: {plan.focus}" if plan.focus else "")]
    for r in revisions:
        evidence.append(f"plan revised: {r['reason']}")
    for s in step_results:
        if s["status"] == "done":
            evidence.append(f"{s['heading']} ({', '.join(s['councils'])}): {s['summary']}")
        else:
            evidence.append(f"{s['heading']}: not available this run - {s['note']}")
    if drafts_held:
        evidence.append("held for approval, nothing sent: " + "; ".join(f"{d['id']} ({d['title']})" for d in drafts_held))
    else:
        evidence.append("no action drafted this run")
    if recalled_ids:
        evidence.append(f"remembered human decisions applied by the Memory agent: {', '.join(recalled_ids)}")

    template = (
        f"Day-one brief for {', '.join(asked_councils or COUNCILS)} - {len(done)} of {len(plan.steps)} checks run, planned by {plan.source}.\n"
        + "".join(f"{n}. {s['heading']} ({', '.join(s['councils'])}): {s['note']}.\n" if s["status"] == "done" else f"{n}. {s['heading']}: not available this run ({s['note'].split(';')[0]}).\n"
                  for n, s in enumerate(step_results, start=1))
        + ("".join(f"Plan revised: {r['reason']}.\n" for r in revisions))
        + (f"Remembered human decisions applied: {', '.join(recalled_ids)}.\n" if recalled_ids else "")
        + ("Held for approval, nothing sent: " + "; ".join(f"{d['id']} ({d['title']})" for d in drafts_held) + ".\n" if drafts_held else "No action was drafted.\n")
        + "Numbers come from the councils' own published files; each row carries a provenance id."
    )
    cliff = next((s for s in done if s["check"] == "contract_cliff"), None)
    cliff_window = None
    if cliff:
        cliff_window = next((a.get("window_days") for a in cliff["artifacts"] if a.get("type") == "run_stats" and a.get("window_days")), None) \
            or cliff["params"].get("window_days") or ctx.settings.cliff_window_days
    instruction = (
        f"Write a day-one brief for the finance lead of the West Surrey shadow authority in about 160 words, covering {', '.join(asked_councils or COUNCILS)}. "
        "One headline line, then one numbered priority per check in the order given, each with the number that justifies it, then one line "
        "naming what is held for approval. Use only the numbers in the evidence. Pairs with identical names are 'shared'; similar names are "
        "'awaiting a human decision'; the match judge's opinions are 'suggestions'; never call a pair confirmed unless the evidence says a human "
        "confirmed it. Say 'no extension date recorded', not 'no extension option'. Residents are SYNTHETIC test residents."
        + (f" The evidence says remembered human decision(s) {', '.join(recalled_ids)} changed an answer: name them." if recalled_ids else "")
        + (" Name any check that was not available." if failures else "")
        + (f" The contracts end within {cliff_window} days of vesting day, not on it: say 'within {cliff_window} days of vesting day'." if cliff_window else "")
    )
    allowed = numbers_in([s["summary"] for s in done] + [s["note"] for s in done] + [len(plan.steps), len(done), len(drafts_held)]
                         + [d["id"] for d in drafts_held] + [d["title"] for d in drafts_held]
                         + [a.get(k) for s in done for a in s["artifacts"] if a.get("type") == "run_stats" for k in ("presented", "needs_human", "total_hard_cliff_gbp", "shared_suppliers_on_cliff")])
    claims = list(HUMAN_ONLY_CLAIMS) + must_name_claims(recalled_ids)
    if any(s["check"] == "policy_gap" for s in done):
        claims += SYNTHETIC_LABEL_CLAIM
    if cliff_window:
        claims += cliff_timing_claims(int(cliff_window))
    # priority N of the brief must only use numbers from check N (in the order the plan ran them)
    sections = [(s["heading"], numbers_in([s.get("summary"), s.get("note")] + list(s.get("recommendations") or [])
                                          + [v for a in s.get("artifacts", []) if a.get("type") == "run_stats" for v in a.values()]
                                          + [a["draft"]["title"] for a in s.get("artifacts", []) if a.get("type") == "draft" and a.get("draft")]))
                for s in step_results]
    draft, draft_bounces = checked_draft(writer, critic, "day-one brief", instruction, evidence, template, allowed, claims, sections)
    bounces += draft_bounces

    recommendations: list[str] = []
    for s in done:
        if s["recommendations"]:
            recommendations.append(f"{s['heading']}: {s['recommendations'][0]}")
    if drafts_held:
        recommendations.append("Approve or reject each held draft with: POST /run input.query = \"Approve draft <id>\" - approval records intent; nothing is sent by this system.")
    if failures:
        recommendations.append(f"{len(failures)} check(s) could not run this time; ask again when the data layer is reachable.")

    return {
        "summary": draft["text"],
        "recommendations": recommendations,
        "artifacts": [
            {"type": "plan", "title": "Plan", "source": plan.source, "model": plan.model, "receipt_id": plan.receipt_id, "focus": plan.focus, "note": plan.note,
             "steps": [{"check": s.check, "params": s.params, "why": s.why} for s in plan.steps], "revisions": revisions},
            {"type": "step_results", "title": "What each check found", "steps": step_results},
            {"type": "generated_text", "title": "Day-one brief", "text": draft["text"], "model": draft["model"], "receipt_id": draft.get("receipt_id"), "mode": draft["mode"]},
            {"type": "run_stats", "steps_planned": len(plan.steps), "steps_run": len(done), "steps_failed": len(failures), "revisions": len(revisions),
             "drafts_held": [d["id"] for d in drafts_held], "recalled_decisions": recalled_ids, "critic_bounces": bounces, "plan_source": plan.source},
        ],
    }
