"""CriticAgent: checks the other agents' work and sends it back when it fails.

Three real checks, each of which can bounce:
- matches: a pair may only be presented as a match if it is confirmed by a human,
  exact, or above the high threshold with Companies House agreement; everything
  else goes back to the Resolver to be relabelled "needs-human". The match judge
  model's opinion never counts: it is a hint for the human, not a pass.
- rows: every row the Writer will cite must carry a provenance id
- drafts: every number in a draft must appear in the evidence it was built from,
  and the draft must not claim more than the evidence says (for example calling
  a pair "confirmed" when no human confirmed it, or dropping the SYNTHETIC label)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.agents.base import Agent
from app.matching import Candidate

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")

Claim = tuple[str, str]   # (regex that must NOT match the draft, why)

# A pair is only ever "shared" (identical names) or "confirmed" by a human. A draft must not
# promote pairs to confirmed, verified or duplicate on its own.
HUMAN_ONLY_CLAIMS: list[Claim] = [
    (r"\bpairs?\s+(?:are|were|is|was|have\s+been|has\s+been)\s+(?:now\s+|already\s+)?(?:confirmed|verified|validated|duplicates?|duplicated)\b",
     "only a human can confirm a pair; say 'shared' for identical names and 'awaiting a human decision' for the rest"),
    (r"\b(?:confirmed|verified|validated)\s+(?:as\s+)?(?:shared|duplicates?|the\s+same|matches|supplier\s+pairs|pairs)\b",
     "only a human can confirm a pair; say 'shared' for identical names and 'awaiting a human decision' for the rest"),
    (r"\b(?:confirmed|verified|validated)\s+(?:duplicate|shared)\s+suppliers?\b",
     "only a human can confirm a pair; say 'shared' for identical names and 'awaiting a human decision' for the rest"),
]

# Residents in the day-one check are made up. Any mention of them must carry the label.
SYNTHETIC_LABEL_CLAIM: list[Claim] = [
    (r"\A(?=.*\b(?:residents?|claimants?|households?|families|people|cases)\b)(?!.*\b(?:synthetic|made[- ]up)\b)",
     "the residents are SYNTHETIC test cases; every mention of them must say so"),
]


def must_name_claims(decision_ids: Sequence[str]) -> list[Claim]:
    """Claims that a briefing must NAME each remembered human decision it was built on.

    When H-MEM recalls a human decision (e.g. mem-1) that changed this answer, the memory must be
    visible in the prose, not only in the trace. Expressed in the same shape as the claims above:
    if the id is absent from the whole draft, the negative-lookahead pattern matches and the draft
    is bounced (so the Writer retries with the reason, else the evidence-only template, which names it).
    """
    claims: list[Claim] = []
    for did in decision_ids:
        claims.append((
            rf"\A(?!.*\b{re.escape(did)}\b)",
            f"a remembered human decision ({did}) changed this answer; the briefing must name it, e.g. 'resolved using decision {did}'",
        ))
    return claims


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
        judged = 0
        for c in cands:
            if c.status in ("confirmed", "split", "needs-human", "unlikely"):
                continue
            ok = c.method == "exact" or (c.method == "fuzzy-high" and c.companies_house)
            if not ok:
                bounced.add(c.key)
                judged += bool(c.model_verdict)
        if bounced:
            hint = f" ({judged} of them carry a match-judge opinion, which is a hint for the human, not a confirmation)" if judged else ""
            self.trace(
                "critique_matches",
                f"{len(cands)} candidate pairs",
                f"rejected {len(bounced)} pairs below the confirmation bar (fuzzy without Companies House, or in the judge band){hint}; returning to Resolver",
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

    def review_draft(self, draft: str, evidence_numbers: set[str], claims: Sequence[Claim] = ()) -> Verdict:
        found = {m.group(0).replace(",", "") for m in _NUM.finditer(draft)}
        allowed = {n.replace(",", "") for n in evidence_numbers}
        unknown = sorted(n for n in found if n not in allowed and not _is_trivial(n))
        reasons: list[str] = []
        if unknown:
            reasons.append(f"numbers not in evidence: {unknown[:6]}")
        flat = " ".join(draft.split())
        for pattern, why in claims:
            m = re.search(pattern, flat, flags=re.IGNORECASE | re.DOTALL)
            if m:
                quoted = m.group(0).strip() or flat[:60]
                reasons.append(f"claim not supported by the evidence: '{quoted[:80]}' - {why}")
        if reasons:
            self.trace("critique_draft", f"draft with {len(found)} numbers", "; ".join(reasons)[:400] + "; returning to Writer",
                       target_agent="Writer", status="rejected", confidence=1.0)
            return Verdict(False, reasons, set(unknown))
        self.trace("critique_draft", f"draft with {len(found)} numbers",
                   "every number traces to the evidence table" + ("; no claim goes beyond the evidence" if claims else ""),
                   target_agent="ApprovalGate", confidence=1.0)
        return Verdict(True)


def _is_trivial(n: str) -> bool:
    # years, small ordinals and dates are allowed in prose
    return bool(re.fullmatch(r"(19|20)\d\d", n)) or (n.isdigit() and int(n) <= 31)
