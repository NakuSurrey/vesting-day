"""ResolverAgent: decides which supplier records across councils are the same organisation.

Normalises names, scores every cross-council pair, applies decisions the
Memory agent recalled, asks Companies House where it can, and - in live mode -
asks the Nemotron match judge about the 0.70-0.92 band. It never marks a pair
confirmed on its own; that needs a human through the ApprovalGate.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.adapters.nightshift import ModelError
from app.agents.base import Agent
from app.matching import Candidate, distinctive_tokens, find_candidates, is_public_body

JUDGE_SYSTEM = (
    "You are a procurement data analyst for merging English councils. Decide whether two supplier "
    "name strings from different councils' payment files refer to the same organisation. Answer with one "
    "word only: SAME, DIFFERENT or UNSURE. Say DIFFERENT when the distinctive part of the name differs "
    "(for example 'EON Energy' vs 'SSE Energy')."
)


class ResolverAgent(Agent):
    name = "Resolver"
    role = "Normalises supplier names, scores cross-council matches, applies remembered decisions and Companies House identity; marks what still needs a human"

    def find_matches(self, spend_rows: list[dict[str, Any]], councils: list[str]) -> list[Candidate]:
        names_by_council: dict[str, set[str]] = {c: set() for c in councils}
        for r in spend_rows:
            if r["council"] in names_by_council:
                names_by_council[r["council"]].add(r["supplier_raw"])
        cands = find_candidates({c: sorted(v) for c, v in names_by_council.items()}, councils)
        unlikely = 0
        for c in cands:
            if c.method == "fuzzy-band" and not (distinctive_tokens(c.a_name) & distinctive_tokens(c.b_name)):
                c.status = "unlikely"
                c.notes.append("distinctive words differ; kept only for audit")
                unlikely += 1
            if is_public_body(c.a_name) or is_public_body(c.b_name):
                c.notes.append("public body, not a consolidation target")
        counts = {m: sum(1 for c in cands if c.method == m) for m in ("exact", "fuzzy-high", "fuzzy-band")}
        self.trace(
            "match_suppliers",
            f"{sum(len(v) for v in names_by_council.values())} distinct supplier names across {len(councils)} councils",
            f"{len(cands)} candidate pairs: {counts['exact']} exact, {counts['fuzzy-high']} fuzzy-high, {counts['fuzzy-band']} in the judge band ({unlikely} of those unlikely: no distinctive word in common)",
            target_agent="Memory",
            confidence=0.95,
        )
        return cands

    def apply_decisions(self, cands: list[Candidate], decisions: dict[str, dict[str, Any]]) -> list[Candidate]:
        n = 0
        for c in cands:
            d = decisions.get(c.key)
            if not d:
                continue
            c.decision_id = d["memory_id"]
            c.status = "confirmed" if d["verdict"] == "same" else "split"
            c.notes.append(f"resolved using decision {d['memory_id']}")
            n += 1
        if n:
            self.trace("apply_decisions", f"{len(decisions)} remembered decisions", f"{n} pairs resolved from memory", confidence=1.0)
        return cands

    def check_companies_house(self, cands: list[Candidate], limit: int = 25) -> None:
        ch = self.ctx.companies_house
        if not ch.available:
            self.trace("companies_house", f"{len(cands)} pairs", "Companies House not available in this mode; identity left to the human gate", confidence=1.0, status="skipped")
            return
        checked = agreed = 0
        for c in cands:
            if c.status != "pending" or checked >= limit:
                continue
            a, b = ch.search(c.a_name), ch.search(c.b_name)
            checked += 1
            if a and b and a.get("company_number") and a.get("company_number") == b.get("company_number"):
                c.companies_house = {"company_number": a["company_number"], "title": a.get("title")}
                c.score = 0.85
                c.notes.append(f"Companies House {a['company_number']} for both names")
                agreed += 1
        self.trace("companies_house", f"{checked} pending pairs looked up", f"{agreed} pairs share a company number", confidence=0.9)

    def judge_band(self, cands: list[Candidate], limit: int = 12) -> None:
        """Live mode: ask the model about the uncertain band. Sample mode: leave them pending."""
        band = [c for c in cands if c.method == "fuzzy-band" and c.status == "pending"][:limit]
        if not band:
            return
        if self.ctx.sample_mode:
            self.trace("judge_matches", f"{len(band)} band pairs", "no model in SAMPLE_MODE; band pairs stay pending for a human", model="sample-mode/template", status="skipped", confidence=1.0)
            return
        for c in band:
            try:
                out = self.ctx.model.complete(JUDGE_SYSTEM, f"A: {c.a_name} ({c.a_council})\nB: {c.b_name} ({c.b_council})\nAnswer:", max_tokens=256)
            except ModelError as e:
                self.trace("judge_matches", f"{c.a_name} vs {c.b_name}", f"model error: {e}", model=self.ctx.model.badge, status="error")
                return
            verdict = (re.search(r"\b(SAME|DIFFERENT|UNSURE)\b", out.text.upper()) or [None, "UNSURE"])[1]
            c.notes.append(f"judge: {verdict} ({out.model}{', receipt ' + out.receipt_id if out.receipt_id else ''})")
            if verdict == "DIFFERENT":
                c.status = "judged-different"
            elif verdict == "SAME":
                c.status = "judged-same"   # still needs the human gate to become confirmed
            self.trace("judge_matches", f"{c.a_name} ({c.a_council}) vs {c.b_name} ({c.b_council})", f"{verdict}", model=out.model, confidence=0.7, receipt_id=out.receipt_id)

    def relabel_bounced(self, cands: list[Candidate], bounced_keys: set[str], reason: str) -> int:
        n = 0
        for c in cands:
            if c.key in bounced_keys and c.status in ("pending", "auto"):
                c.status = "needs-human"
                c.notes.append(reason)
                n += 1
        self.trace("relabel", f"{len(bounced_keys)} pairs returned by Critic", f"{n} pairs marked needs-human; nothing asserted below threshold",
                   target_agent="Critic", confidence=1.0, retry_count=1)
        return n

    @staticmethod
    def to_rows(cands: list[Candidate], spend_index: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for c in cands:
            a = spend_index.get((c.a_council, c.a_name), {})
            b = spend_index.get((c.b_council, c.b_name), {})
            rows.append({
                "pair": c.key,
                "a_council": c.a_council, "a_name": c.a_name, "a_total_gbp": a.get("total_gbp"), "a_payments": a.get("n_payments"),
                "a_provenance": a.get("example_provenance"), "a_source": a.get("source_file"),
                "b_council": c.b_council, "b_name": c.b_name, "b_total_gbp": b.get("total_gbp"), "b_payments": b.get("n_payments"),
                "b_provenance": b.get("example_provenance"), "b_source": b.get("source_file"),
                "combined_gbp": round(float(a.get("total_gbp") or 0) + float(b.get("total_gbp") or 0), 2),
                "similarity": c.similarity, "method": c.method, "score": c.score, "status": c.status,
                "decision_id": c.decision_id, "companies_house": c.companies_house, "notes": c.notes,
                "public_body": is_public_body(c.a_name) or is_public_body(c.b_name),
            })
        return rows
