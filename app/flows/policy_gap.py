"""Flow: Council Tax Support policy gap.

Router -> Researcher (the clause table extracted from each council's scheme PDF,
with page citations) -> Critic (every clause must cite a page) -> comparison
grid -> day-one check against clearly labelled SYNTHETIC residents -> Writer
(options note) -> Critic (numbers) -> ApprovalGate (held).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.agents.approval import ApprovalGateAgent
from app.agents.base import RunContext
from app.agents.critic import SYNTHETIC_LABEL_CLAIM, CriticAgent
from app.agents.researcher import ResearcherAgent
from app.agents.writer import WriterAgent
from app.flows.common import checked_draft, gbp, numbers_in

CLAUSE_LABELS = {
    "capital_limit_gbp": "Capital limit (GBP) above which no support is paid",
    "band_cap": "Council Tax band at which support is capped",
    "min_award_gbp_week": "Minimum weekly award (GBP)",
    "max_support_pct": "Maximum support as % of liability (working age)",
    "earnings_disregard_gbp_week": "Standard earnings disregard, single claimant (GBP/week)",
    "non_dep_deduction_top_gbp_week": "Highest non-dependant deduction (GBP/week)",
    "backdating_weeks": "Maximum backdating (weeks)",
    "second_adult_rebate": "Second adult rebate available to working age",
    "excluded_bands": "Valuation bands excluded from the scheme",
}


def _load_residents(data_dir: Path) -> list[dict[str, Any]]:
    p = data_dir / "residents_synthetic.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run(ctx: RunContext, sources: dict[str, Any]) -> dict[str, Any]:
    councils = [c for c in (ctx.councils or ["Woking", "Guildford"]) if c in ("Woking", "Guildford")] or ["Woking", "Guildford"]
    researcher = ResearcherAgent(ctx)
    critic = CriticAgent(ctx)
    writer = WriterAgent(ctx)
    gate = ApprovalGateAgent(ctx)

    clauses = researcher.policy_clauses(councils)
    if not clauses:
        return {"summary": "No Council Tax Support clauses are loaded for these councils (Waverley's scheme is not in the data set yet).",
                "recommendations": ["Ask about Woking and Guildford, whose 2026 schemes are loaded."], "artifacts": []}
    verdict = critic.review_rows(clauses, required=("page", "source_pdf"))
    cited = [r for r in clauses if r.get("page") and r.get("source_pdf")]

    grid: dict[str, dict[str, dict[str, Any]]] = {}
    for r in cited:
        grid.setdefault(r["clause_key"], {})[r["council"]] = r
    diffs: list[dict[str, Any]] = []
    same: list[str] = []
    for key, by_c in grid.items():
        vals = {c: (by_c[c].get("value_num") if by_c[c].get("value_num") not in (None, "") else by_c[c].get("value_text")) for c in councils if c in by_c}
        if len(vals) < len(councils):
            continue
        distinct = {str(v).strip().lower() for v in vals.values()}
        if len(distinct) > 1:
            diffs.append({"clause_key": key, "label": CLAUSE_LABELS.get(key, key), **{c: by_c[c] for c in councils}})
        else:
            same.append(key)
    n_keys = len(grid)
    critic.trace("compare_clauses", f"{n_keys} clause keys across {', '.join(councils)}", f"{len(diffs)} clauses differ, {len(same)} agree", target_agent="Writer", confidence=1.0)

    # day-one check on labelled synthetic residents
    residents = _load_residents(ctx.settings.data_dir)
    impacts: list[dict[str, Any]] = []
    cap = {c: grid.get("capital_limit_gbp", {}).get(c, {}).get("value_num") for c in councils}
    pct = {c: grid.get("max_support_pct", {}).get(c, {}).get("value_num") for c in councils}
    min_award = {c: grid.get("min_award_gbp_week", {}).get(c, {}).get("value_num") for c in councils}
    excluded = {c: (grid.get("excluded_bands", {}).get(c, {}).get("value_text") or "") for c in councils}
    for res in residents:
        capital = float(res.get("capital_gbp") or 0)
        band = (res.get("band") or "").strip().upper()
        liability = float(res.get("weekly_liability_gbp") or 0)
        row = {"resident_id": res["resident_id"], "label": "SYNTHETIC", "home_council": res.get("home_council"), "band": band,
               "capital_gbp": capital, "weekly_liability_gbp": liability, "household": res.get("household"), "treatment": {}}
        for c in councils:
            if cap.get(c) is None:
                continue
            reasons = []
            band_excluded = band in {b.strip() for b in excluded[c].replace(" and ", ",").split(",")} if excluded[c] and not excluded[c].startswith("none") else False
            if band_excluded:
                reasons.append(f"band {band} excluded")
            if capital > float(cap[c]):
                reasons.append(f"capital above {cap[c]:.0f}")
            award = 0.0 if reasons else round(liability * float(pct[c] or 100) / 100, 2)
            if not reasons and min_award.get(c) is not None and award < float(min_award[c]):
                reasons.append(f"award below minimum {min_award[c]:.2f}")
                award = 0.0
            row["treatment"][c] = {"eligible": not reasons, "max_weekly_award_gbp": award, "why": reasons}
        awards = {v["max_weekly_award_gbp"] for v in row["treatment"].values()}
        row["differs_between_councils"] = len(awards) > 1
        impacts.append(row)
    affected = [r for r in impacts if r["differs_between_councils"]]
    if residents:
        critic.trace("day_one_check", f"{len(residents)} SYNTHETIC residents against capital limit and support rate", f"{len(affected)} would be treated differently depending on which legacy scheme applies", confidence=1.0, synthetic=True)

    evidence = [f"{n_keys} clause keys compared across {', '.join(councils)} ({len(cited)} cited values); {len(diffs)} differ, {len(same)} agree"] + [
        f"{d['label']}: " + "; ".join(f"{c} = {d[c].get('value_text') or d[c].get('value_num')} (p.{d[c]['page']} of {Path(d[c]['source_pdf']).name})" for c in councils) for d in diffs
    ] + ([f"{len(affected)} of {len(residents)} SYNTHETIC test residents would be treated differently on day one"] if residents else [])

    template = (
        f"Council Tax Support: where {' and '.join(councils)} differ.\n"
        f"Of {n_keys} clauses compared, {len(diffs)} differ and {len(same)} agree.\n"
        + "".join(f"- {d['label']}: " + "; ".join(f"{c} {d[c].get('value_text') or d[c].get('value_num')} (p.{d[c]['page']})" for c in councils) + ".\n" for d in diffs)
        + (f"Day-one check on {len(residents)} SYNTHETIC residents: {len(affected)} would get a different answer depending on which legacy scheme applied.\n" if residents else "")
        + "The new authority must adopt one working-age scheme before the first bills of 2027/28; these are the clauses the decision has to settle. Every value above cites a page of the published scheme."
    )
    allowed = numbers_in([len(cited), n_keys, len(diffs), len(same), len(residents), len(affected)] + [r.get("value_num") for r in cited] + [r.get("value_text") for r in cited] + [r.get("page") for r in cited])
    draft, _ = checked_draft(writer, critic, "options note",
                             f"Write a 120-word options note for the finance lead on the Council Tax Support clauses that differ between {' and '.join(councils)}. "
                             "The residents in the day-one check are SYNTHETIC test cases: if you mention them, call them SYNTHETIC test residents.",
                             evidence, template, allowed, SYNTHETIC_LABEL_CLAIM if residents else ())
    held = gate.hold("options_note", f"CTS harmonisation: {', '.join(councils)}", draft["text"], draft["model"], [f"{r['source_pdf']}#p{r['page']}" for r in cited], draft.get("receipt_id"))

    summary = (f"Council Tax Support in {' and '.join(councils)}: {len(diffs)} of {n_keys} compared clauses differ ("
               + ", ".join(d["label"].split(" (")[0] for d in diffs) + f"). "
               + (f"{len(affected)} of {len(residents)} SYNTHETIC test residents would be treated differently on day one. " if residents else "")
               + f"An options note is drafted and held for approval as {held['id']}. All clause values cite a page of each council's published scheme.")
    return {
        "summary": summary,
        "recommendations": [
            "Put the differing clauses to the shadow authority's finance committee as the decisions needed before the 2027/28 scheme is adopted.",
            f"Approve or reject the held note with: POST /run input.query = \"Approve draft {held['id']}\"",
            "Residents shown are SYNTHETIC test cases, labelled as such; no real claimant data is used.",
        ],
        "artifacts": [
            {"type": "clause_grid", "title": "Clause by council (with page citations)", "clauses": cited, "differences": diffs, "agreements": same,
             "provenance": "data/sample/policy_clauses.csv -> data/raw/<council>/<scheme pdf>#page"},
            {"type": "table", "title": "Day-one check (SYNTHETIC residents)", "synthetic": True, "rows": impacts},
            {"type": "draft", "title": "Held for approval", "draft": held},
        ],
    }
