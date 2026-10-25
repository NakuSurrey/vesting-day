"""CriticAgent: checks the other agents' work and sends it back when it fails.

Three real checks, each of which can bounce:
- matches: a pair may only be presented as a match if it is confirmed by a human,
  exact, or above the high threshold with Companies House agreement; everything
  else goes back to the Resolver to be relabelled "needs-human"
- rows: every row the Writer will cite must carry a provenance id
- drafts: every number in a draft must appear in the evidence it was built from
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import Agent
from app.matching import Candidate

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")


@dataclass
class Verdict:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    bounced: set[str] = field(default_factory=set)


class CriticAgent(Agent):
    name = "Critic"
    role = "Validates provenance and thresholds on every result; rejects and returns work that does not clear the bar (one real bounce when needed)"

    def review_matches(self, cands: list[Candidate]) -> Verdict:
        bounced: set[str] = set()
        for c in cands:
            if c.status in ("confirmed", "split", "judged-different", "needs-human", "unlikely"):
                continue
            ok = c.method == "exact" or (c.method == "fuzzy-high" and c.companies_house) or c.status == "judged-same"
            if not ok:
                bounced.add(c.key)
        if bounced:
            self.trace(
                "critique_matches",
                f"{len(cands)} candidate pairs",
                f"rejected {len(bounced)} pairs below the confirmation bar (fuzzy without Companies House, or in the judge band); returning to Resolver",
                target_agent="Resolver", confidence=1.0, status="rejected",
            )
            return Verdict(False, ["pairs below threshold must not be presented as matches"], bounced)
        self.trace("critique_matches", f"{len(cands)} candidate pairs", "all presented matches are exact, confirmed, or Companies-House-backed", target_agent="Writer", confidence=1.0)
        return Verdict(True)

    def review_rows(self, rows: list[dict[str, Any]], required: tuple[str, ...] = ("provenance_id",)) -> Verdict:
        bad = [r for r in rows if any(not r.get(k) for k in required)]
        if bad:
            self.trace("critique_rows", f"{len(rows)} rows", f"{len(bad)} rows missing {required}; returning to Researcher", target_agent="Researcher", status="rejected", confidence=1.0)
            return Verdict(False, [f"{len(bad)} rows lack {required}"], {str(r.get('contract_ref') or r.get('pair') or i) for i, r in enumerate(bad)})
        self.trace("critique_rows", f"{len(rows)} rows", "every row carries a provenance id", target_agent="Writer", confidence=1.0)
        return Verdict(True)

    def review_draft(self, draft: str, evidence_numbers: set[str]) -> Verdict:
        found = {m.group(0).replace(",", "") for m in _NUM.finditer(draft)}
        allowed = {n.replace(",", "") for n in evidence_numbers}
        unknown = sorted(n for n in found if n not in allowed and not _is_trivial(n))
        if unknown:
            self.trace("critique_draft", f"draft with {len(found)} numbers", f"{len(unknown)} numbers not in the evidence: {unknown[:6]}; returning to Writer", target_agent="Writer", status="rejected", confidence=1.0)
            return Verdict(False, [f"numbers not in evidence: {unknown[:6]}"], set(unknown))
        self.trace("critique_draft", f"draft with {len(found)} numbers", "every number traces to the evidence table", target_agent="ApprovalGate", confidence=1.0)
        return Verdict(True)


def _is_trivial(n: str) -> bool:
    # years, small ordinals and dates are allowed in prose
    return bool(re.fullmatch(r"(19|20)\d\d", n)) or (n.isdigit() and int(n) <= 31)
