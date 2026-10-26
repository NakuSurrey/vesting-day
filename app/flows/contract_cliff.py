"""Flow: the contract cliff around vesting day.

Router -> Researcher (registers, contracts ending within the window, contracts
with no end date) -> Critic (provenance, recorded extension dates) -> Resolver (which
cliff suppliers also serve another council) -> Writer (one novation letter for
the largest contract, evidence-bound) -> Critic (numbers) -> ApprovalGate (held).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agents.approval import ApprovalGateAgent
from app.agents.base import RunContext
from app.agents.critic import CriticAgent
from app.agents.memory import MemoryAgent
from app.agents.researcher import ResearcherAgent
from app.agents.resolver import ResolverAgent
from app.agents.writer import WriterAgent
from app.flows.common import checked_draft, gbp, numbers_in
from app.matching import normalise


def run(ctx: RunContext, sources: dict[str, Any]) -> dict[str, Any]:
    councils = ctx.councils or ["Woking", "Guildford", "Waverley"]
    vesting_day = ctx.settings.vesting_day
    window_days = int(ctx.params.get("window_days") or ctx.settings.cliff_window_days)
    researcher = ResearcherAgent(ctx)
    critic = CriticAgent(ctx)
    resolver = ResolverAgent(ctx)
    writer = WriterAgent(ctx)
    gate = ApprovalGateAgent(ctx)
    memory = MemoryAgent(ctx)

    summary_rows = researcher.contracts_summary(councils)
    cliff = researcher.contracts_near(councils, vesting_day, window_days)
    # an empty window is not an answer: the Critic asks the Researcher to widen it (doubling, up to a year,
    # at most three times). The window the question asked for stays the headline; the widened one is labelled.
    asked_window, widened_to, attempts = window_days, None, 0
    while not cliff and window_days < 365 and attempts < 3:
        wider = min(window_days * 2, 365)
        critic.trace("critique_coverage", f"0 contracts within {window_days} days of {vesting_day} for {', '.join(councils)}",
                     f"an empty window is not an answer; asking the Researcher to widen to {wider} days", target_agent="Researcher",
                     status="needs_revision", confidence=1.0, asked_window_days=asked_window, widen_to=wider)
        attempts += 1
        window_days = wider
        cliff = researcher.contracts_near(councils, vesting_day, window_days, retry=attempts)
        widened_to = window_days
    no_end = researcher.contracts_without_end_date(councils)

    verdict = critic.review_rows(cliff)
    if not verdict.accepted:
        cliff = [r for r in cliff if r.get("provenance_id")]

    vd = date.fromisoformat(vesting_day)
    for r in cliff:
        end = date.fromisoformat(r["end_date"])
        r["days_from_vesting_day"] = (end - vd).days
        ext = r.get("max_extension_end") or ""
        r["extension_past_vesting_day"] = bool(ext) and ext > vesting_day
        r["phase"] = "ends before vesting day" if end < vd else "ends on or after vesting day"
        r["value_gbp"] = r.get("total_value_gbp") or r.get("annual_value_gbp")

    # cross-council exposure: does a cliff supplier also appear in another council's spend?
    spend = researcher.supplier_spend(["Woking", "Guildford", "Waverley"])
    by_norm: dict[str, set[str]] = {}
    for s in spend:
        by_norm.setdefault(normalise(s["supplier_raw"]), set()).add(s["council"])
    shared = 0
    for r in cliff:
        others = sorted(by_norm.get(normalise(r["supplier_raw"]), set()) - {r["council"]})
        r["also_paid_by"] = others
        shared += bool(others)
    resolver.trace("cross_council_exposure", f"{len(cliff)} cliff contracts vs spend of 3 councils", f"{shared} cliff suppliers are also paid by another council", confidence=0.9)

    # a recorded extension date past vesting day takes a contract off the hard cliff; a blank
    # extension field means none is recorded in the register, not that none exists
    hard = [r for r in cliff if not r["extension_past_vesting_day"]]
    with_option = [r for r in cliff if r["extension_past_vesting_day"]]
    critic.trace("classify_cliff", f"{len(cliff)} contracts in window", f"{len(hard)} with no extension date recorded past {vesting_day} (hard cliff); {len(with_option)} have an extension date recorded past it; {len(no_end)} contracts have no usable end date and are listed separately",
                 target_agent="Writer", confidence=1.0)

    total_value = round(sum(float(r["value_gbp"] or 0) for r in hard), 2)
    per_council = {c: {"contracts": sum(1 for r in hard if r["council"] == c), "value_gbp": round(sum(float(r["value_gbp"] or 0) for r in hard if r["council"] == c), 2)} for c in councils}
    hard.sort(key=lambda r: (-(float(r["value_gbp"] or 0)), r["end_date"]))
    target = hard[0] if hard else None

    evidence = [
        f"vesting day {vesting_day}; window plus or minus {window_days} days"
        + (f" (the question asked for {asked_window} days; no contract ended in that window, so the Researcher widened it)" if widened_to else ""),
        f"{len(hard)} contracts end in the window with no extension date recorded past vesting day (the registers often leave the extension field blank, so an unrecorded option may still exist), total stated value {gbp(total_value)}",
    ] + [f"{c}: {v['contracts']} contracts, {gbp(v['value_gbp'])}" for c, v in per_council.items()] + [
        f"{len(with_option)} further contracts in the window have an extension date recorded past vesting day",
        f"{len(no_end)} register entries have no usable end date",
    ]
    if target:
        evidence.append(f"largest: {target['title']} ({target['council']}, ref {target['contract_ref']}, supplier {target['supplier_raw']}, ends {target['end_date']}, value {gbp(target['value_gbp'])}, provenance {target['provenance_id']})")

    draft_text = ""
    held = None
    if target:
        letter_template = (
            f"Draft - not sent. For approval by the {target['council']} procurement lead.\n\n"
            f"To: {target['supplier_raw']}\n"
            f"Subject: Contract {target['contract_ref']} - {target['title']} - arrangements at vesting day\n\n"
            f"Dear supplier,\n\n"
            f"Our register shows that contract {target['contract_ref']} ({target['title']}) with {target['council']} Borough Council "
            f"ends on {target['end_date']}, which is {abs(target['days_from_vesting_day'])} days "
            f"{'before' if target['days_from_vesting_day'] < 0 else 'after'} the vesting day of the new West Surrey authority ({vesting_day}). "
            f"The register states a contract value of {gbp(target['value_gbp'])}.\n\n"
            f"Ahead of vesting day we need to agree one of: novation of this contract to the new authority, "
            f"a short extension to align with the successor arrangements, or planned expiry. "
            f"Please confirm your preferred route and any conditions by return.\n\n"
            f"This letter is a draft prepared from the published contracts register "
            f"(entry {target['provenance_id']}) and requires human approval before it is sent."
        )
        allowed = numbers_in([vesting_day, target["end_date"], target["value_gbp"], abs(target["days_from_vesting_day"]), target["contract_ref"], target["provenance_id"], window_days, asked_window, total_value, len(hard), len(with_option), len(no_end)]
                             + [v["contracts"] for v in per_council.values()] + [v["value_gbp"] for v in per_council.values()])
        draft, _ = checked_draft(writer, critic, "novation letter",
                                 "Write a short letter to the supplier of the largest contract ending near vesting day, asking them to confirm novation, extension or expiry. "
                                 "It is a draft for human approval: say what the register shows, do not state what will happen, and keep the 'Draft - not sent' opening.",
                                 evidence, letter_template, allowed)
        held = gate.hold("novation_letter", f"{target['contract_ref']} {target['title']}", draft["text"], draft["model"], [target["provenance_id"]], draft.get("receipt_id"), recipient=target["supplier_raw"])
        draft_text = draft["text"]

    summary = (
        (f"No contract ends within {asked_window} days of vesting day {vesting_day} for {', '.join(councils)}; the window was widened to {widened_to} days to find the nearest. " if widened_to else "")
        + f"Contract cliff around vesting day {vesting_day} (plus or minus {window_days} days) for {', '.join(councils)}: "
        f"{len(hard)} contracts end with no extension date recorded past vesting day, stated value {gbp(total_value)} "
        f"({'; '.join(f'{c} {v['contracts']} / {gbp(v['value_gbp'])}' for c, v in per_council.items())}). "
        f"{len(with_option)} more have an extension date recorded past vesting day; {len(no_end)} register entries have no usable end date. "
        f"{shared} cliff suppliers are also paid by another of the three councils. "
        + (f"One action drafted and held for approval: {held['id']} ({target['title']}, {target['council']})." if held else "No contract in the window; nothing drafted.")
    )
    return {
        "summary": summary,
        "recommendations": [
            f"Review the {min(5, len(hard))} largest hard-cliff contracts first: " + "; ".join(f"{r['title']} ({r['council']}, ends {r['end_date']}, {gbp(r['value_gbp'])})" for r in hard[:5]),
            f"Approve or reject the held draft with: POST /run input.query = \"Approve draft {held['id']}\"" if held else "Widen the window (e.g. 'contracts ending within 12 months of vesting day') to find candidates.",
            "Treat the no-end-date entries as a data-quality action for each council before vesting day.",
        ],
        "artifacts": [
            {"type": "table", "title": f"Hard cliff: contracts ending within {window_days} days of {vesting_day}, no extension date recorded past it", "count": len(hard), "rows": hard[:80],
             "provenance": "data/sample/contracts.csv -> data/raw/<council>/<register> (provenance_id = council:file:row)"},
            {"type": "table", "title": "In window but with an extension date recorded past vesting day", "count": len(with_option), "rows": with_option[:40]},
            {"type": "table", "title": "Register entries with no usable end date", "count": len(no_end), "rows": no_end[:40]},
            {"type": "table", "title": "Register summary per council", "rows": summary_rows},
            {"type": "draft", "title": "Held for approval", "draft": held},
            {"type": "run_stats", "per_council": per_council, "total_hard_cliff_gbp": total_value, "shared_suppliers_on_cliff": shared,
             "asked_window_days": asked_window, "window_days": window_days, "widened_to": widened_to},
        ],
    }
