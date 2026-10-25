"""Flow: supplier overlap across councils.

Router -> Researcher (federated spend per supplier) -> Resolver (match) ->
Memory (recall human decisions) -> Resolver (apply; Companies House; judge band)
-> Critic (reject anything below the bar) -> Resolver (relabel, retry 1)
-> Critic (pass) -> Writer (briefing from evidence) -> Critic (numbers) -> output.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import RunContext
from app.agents.critic import CriticAgent
from app.agents.memory import MemoryAgent
from app.agents.researcher import ResearcherAgent
from app.agents.resolver import ResolverAgent
from app.agents.writer import WriterAgent
from app.flows.common import badge_line, gbp, numbers_in, window_badges


def run(ctx: RunContext, sources: dict[str, Any]) -> dict[str, Any]:
    councils = ctx.councils if len(ctx.councils) >= 2 else ["Woking", "Guildford", "Waverley"]
    researcher = ResearcherAgent(ctx)
    resolver = ResolverAgent(ctx)
    memory = MemoryAgent(ctx)
    critic = CriticAgent(ctx)
    writer = WriterAgent(ctx)

    windows = window_badges(researcher.council_windows(councils), sources)
    spend = researcher.supplier_spend(councils)
    spend_index = {(r["council"], r["supplier_raw"]): r for r in spend}

    cands = resolver.find_matches(spend, councils)
    decisions = memory.recall_decisions(cands)
    resolver.apply_decisions(cands, decisions)
    resolver.check_companies_house(cands)
    resolver.judge_band(cands)

    verdict = critic.review_matches(cands)
    bounces = 0
    if not verdict.accepted:
        bounces = 1
        resolver.relabel_bounced(cands, verdict.bounced, "below confirmation bar; needs a human decision")
        verdict = critic.review_matches(cands)

    rows = resolver.to_rows(cands, spend_index)
    rows.sort(key=lambda r: -(r["combined_gbp"] or 0))
    presented = [r for r in rows if r["status"] in ("auto", "confirmed", "judged-same")]
    from_memory = [r for r in rows if r["decision_id"]]
    needs_human = [r for r in rows if r["status"] in ("needs-human", "pending")]
    unlikely = [r for r in rows if r["status"] == "unlikely"]
    split = [r for r in rows if r["status"] in ("split", "judged-different")]
    consolidation = [r for r in presented if not r["public_body"]][:5]
    shared_spend = round(sum(r["combined_gbp"] for r in presented), 2)
    top = presented[:5]

    evidence = [badge_line(b) for b in windows] + [
        f"{len(presented)} supplier pairs are shared with confidence (exact after normalisation, human-confirmed, or Companies-House-backed)",
        f"{len(from_memory)} of those were resolved using remembered human decisions ({', '.join(sorted({r['decision_id'] for r in from_memory}))})" if from_memory else "0 pairs came from remembered decisions",
        f"{len(needs_human)} candidate pairs need a human decision before they can be called the same supplier",
        f"{len(split)} pairs were judged or confirmed to be different organisations",
        f"combined spend across the shared pairs in the councils' published windows: {gbp(shared_spend)}",
    ] + [f"top shared supplier {i + 1}: {r['a_name']} ({r['a_council']}, {gbp(r['a_total_gbp'])}) and {r['b_name']} ({r['b_council']}, {gbp(r['b_total_gbp'])}), combined {gbp(r['combined_gbp'])}, status {r['status']}{', ' + r['notes'][0] if r['notes'] else ''}"
         for i, r in enumerate(top)]

    template = (
        f"Supplier overlap across {', '.join(councils)}.\n"
        f"Windows: " + "; ".join(badge_line(b) for b in windows) + ".\n"
        f"{len(presented)} supplier pairs are shared with confidence; {len(from_memory)} of them are resolved from remembered human decisions"
        f"{' (' + ', '.join(sorted({r['decision_id'] for r in from_memory})) + ')' if from_memory else ''}. "
        f"{len(needs_human)} candidate pairs still need a human to confirm or split, and {len(split)} pairs are recorded as different organisations.\n"
        f"Combined published spend across the shared pairs is {gbp(shared_spend)}.\n"
        + "Largest shared suppliers: " + "; ".join(f"{r['a_name']} / {r['b_name']} ({gbp(r['combined_gbp'])}, {r['status']})" for r in top) + ".\n"
        "Numbers come from the councils' own published payment files; each row carries a provenance id."
    )
    draft = writer.draft("briefing", f"Summarise the supplier overlap across {', '.join(councils)} for the finance lead in 120 words", evidence, template)
    dv = critic.review_draft(draft["text"], numbers_in([shared_spend, len(presented), len(from_memory), len(needs_human), len(split), len(cands)]
                                                          + [r["combined_gbp"] for r in top] + [r["a_total_gbp"] for r in top] + [r["b_total_gbp"] for r in top]
                                                          + [b.get("rows_published") for b in windows] + [b.get("total_gbp") for b in windows]
                                                          + [b.get("distinct_suppliers") for b in windows]))
    if not dv.accepted:
        bounces += 1
        draft = writer.draft("briefing", "Rewrite using only the evidence numbers", evidence, template, retry=1)

    recommendations = [
        f"Confirm or split the {min(3, len(needs_human))} largest unconfirmed pairs: " + "; ".join(
            f"'{r['a_name']}' ({r['a_council']}) vs '{r['b_name']}' ({r['b_council']}) - combined {gbp(r['combined_gbp'])}, similarity {r['similarity']}" for r in needs_human[:3])
        if needs_human else "No unconfirmed candidate pairs remain.",
        f"Start supplier consolidation with the largest shared commercial suppliers (public bodies excluded): " + "; ".join(f"{r['a_name']} ({gbp(r['combined_gbp'])})" for r in consolidation),
        "To record a decision: POST /run with input.query = \"Confirm that '<name A>' (<council>) is the same supplier as '<name B>' (<council>)\" - the Memory agent will apply it to every later answer.",
    ]
    return {
        "summary": draft["text"],
        "recommendations": recommendations,
        "artifacts": [
            {"type": "period_badges", "title": "What each council has published (per-council window)", "data": windows},
            {"type": "table", "title": "Shared suppliers (presented)", "count": len(presented), "columns": list(presented[0].keys()) if presented else [], "rows": presented[:60],
             "provenance": "data/sample/spend.csv -> data/raw/<council>/* (provenance_id = council:file:row)"},
            {"type": "table", "title": "Candidates needing a human decision", "count": len(needs_human), "rows": needs_human[:40]},
            {"type": "table", "title": "Unlikely pairs (no distinctive word in common; kept for audit)", "count": len(unlikely), "rows": unlikely[:20]},
            {"type": "memory", "title": "Decisions recalled from H-MEM", "decisions": decisions, "ledger_tail": memory.ledger_tail(6)},
            {"type": "generated_text", "title": "Briefing", "text": draft["text"], "model": draft["model"], "receipt_id": draft.get("receipt_id"), "mode": draft["mode"]},
            {"type": "run_stats", "candidates": len(cands), "presented": len(presented), "needs_human": len(needs_human), "unlikely": len(unlikely), "critic_bounces": bounces, "councils": councils},
        ],
    }
