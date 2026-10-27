"""RouterAgent: turns a free-text request into one of the supported flows.

People ask in their own words. The router scores each flow by the
phrases it recognises, picks the best, and returns a structured "unsupported"
when nothing fits - never a guess dressed up as an answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import Agent, UnsupportedRequest

COUNCILS = ("Woking", "Guildford", "Waverley")

FLOWS: dict[str, dict[str, Any]] = {
    # first on purpose: when a broad question ties with a specific flow, the Planner takes it
    "day_one_brief": {
        "description": "A broad question answered by planning: the Planner chooses which checks to run (contracts, suppliers, Council Tax Support), delegates them, assesses the results and writes one prioritised brief",
        "phrases": ["risk", "risks", "brief", "briefing", "summarise", "summarize", "summary", "overview", "priorities", "priority",
                    "prioritise", "prioritize", "biggest", "most urgent", "what should", "where should", "where do i start", "where to start",
                    "everything", "readiness", "ready for", "prepare for", "day-one brief", "day one brief", "merger", "integration",
                    "transition", "what happens", "what changes", "what matters", "worry", "exposure", "state of play", "big picture"],
        "example": "What are the biggest risks on vesting day?",
    },
    "supplier_overlap": {
        "description": "Which suppliers two or three of the councils share, with spend, and which matches still need a human",
        "phrases": ["supplier", "suppliers", "vendor", "vendors", "overlap", "share", "shared", "common", "duplicate",
                    "reconcile", "conflict", "same supplier", "match", "payee", "payees", "spend with",
                    "company", "companies", "firm", "firms", "paid by", "both pay", "pay the same"],
        "example": "Which suppliers do Woking, Guildford and Waverley share?",
    },
    "confirm_match": {
        "description": "Record a human decision that two supplier records are (or are not) the same organisation",
        "phrases": ["confirm", "is the same as", "are the same", "same organisation", "same company", "split",
                    "not the same", "different organisation"],
        "example": "Confirm that 'UNIT 4 BUSINESS SOFTWARE LTD' (Waverley) is the same supplier as 'Unit4 Business Software Ltd' (Guildford)",
    },
    "contract_cliff": {
        "description": "Contracts that end or need novation around vesting day (1 April 2027), across the councils' registers",
        "phrases": ["contract", "contracts", "cliff", "expire", "expiring", "expiry", "end date", "ending", "novation",
                    "novate", "vesting day", "renew", "register", "procurement",
                    "deal", "deals", "agreement", "agreements", "run out", "lapse", "terminate"],
        "example": "Which contracts end within six months of vesting day?",
    },
    "policy_gap": {
        "description": "Where the councils' Council Tax Support schemes differ, clause by clause, and what a resident hits on day one",
        "phrases": ["council tax support", "council tax reduction", "cts", "ctr", "policy", "policies", "scheme",
                    "schemes", "clause", "resident", "residents", "day one", "day-one", "harmonis", "harmoniz", "gap",
                    "capital limit", "band cap", "disregard", "non-dependant", "backdat"],
        "example": "Where do the Council Tax Support schemes differ between Woking and Guildford?",
    },
    "approve_draft": {
        "description": "Approve or reject a draft that the Writer produced and the ApprovalGate is holding",
        "phrases": ["approve draft", "reject draft", "approve the draft", "approve ", "reject "],
        "example": "Approve draft draft-1",
    },
}


_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "first": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty-four": 24}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}   # 30-day months: "six months" = 180, the default
_WORDS = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_WINDOW = re.compile(r"\b(?:(\d+)[\s-]*|(" + _WORDS + r")[\s-]+)(day|week|month|quarter|year)s?\b")


def window_days_in(q: str) -> int | None:
    """The time window a question asks for, in days: 'within a year' -> 365, 'three months' -> 90.

    People ask in their own words, so the window is read from digits or number words with any
    of days, weeks, months or years. Returns None when the question names no window.
    """
    q = q.lower()
    if re.search(r"\bhalf[\s-]+(?:a[\s-]+)?year\b", q):
        return 180
    for m in _WINDOW.finditer(q):
        n = int(m.group(1)) if m.group(1) else _NUMBER_WORDS[m.group(2)]
        days = n * _UNIT_DAYS[m.group(3)]
        if 1 <= days <= 3650:
            return days
    return None


@dataclass
class Route:
    flow: str
    confidence: float
    councils: list[str]
    params: dict[str, Any] = field(default_factory=dict)


class RouterAgent(Agent):
    name = "Router"
    role = "Classifies a free-text request into a supported flow, extracts councils and parameters, or returns a structured unsupported error"

    def route(self, query: str, councils_hint: list[str] | None, params_hint: dict[str, Any]) -> Route:
        q = query.lower()
        scores: dict[str, float] = {}
        for flow, spec in FLOWS.items():
            hits = [p for p in spec["phrases"] if p in q]
            # longer phrases are stronger evidence
            scores[flow] = sum(len(p.split()) for p in hits)
        # explicit override
        if params_hint.get("flow") in FLOWS:
            best, conf = params_hint["flow"], 1.0
        else:
            best = max(scores, key=lambda f: scores[f]) if scores else ""
            top = scores.get(best, 0)
            conf = min(0.99, 0.5 + 0.12 * top) if top else 0.0
            # tie-breakers: confirm beats overlap when 'confirm' or 'same' appears
            if scores.get("confirm_match", 0) and ("confirm" in q or "same" in q or "split" in q):
                best, conf = "confirm_match", max(conf, 0.9)
            if scores.get("approve_draft", 0) and re.search(r"\b(approve|reject)\b.*\bdraft", q):
                best, conf = "approve_draft", 0.95
        if not best or conf < 0.55:
            supported = "; ".join(f"{k}: {v['example']}" for k, v in FLOWS.items())
            self.trace("classify", query, "unsupported request", confidence=conf, status="rejected", supported=list(FLOWS))
            raise UnsupportedRequest(f"I can answer these kinds of request - {supported}")

        councils = list(councils_hint or [c for c in COUNCILS if c.lower() in q]) or list(COUNCILS)
        councils = [c for c in COUNCILS if c in councils]
        params = dict(params_hint)
        if best == "confirm_match":
            params.update(self._parse_confirm(query))
        if best == "approve_draft":
            m = re.search(r"\b(approve|reject)\b.*?\b(draft-\d+)", q)
            if m:
                params["decision"] = m.group(1)
                params["draft_id"] = m.group(2)
        if best == "contract_cliff":
            days = window_days_in(q)
            if days:
                params.setdefault("window_days", days)   # an explicit window_days in the request wins
        self.trace("classify", query, f"flow={best} councils={councils} params={params}", target_agent=self._target(best), confidence=round(conf, 2))
        return Route(flow=best, confidence=round(conf, 2), councils=councils, params=params)

    @staticmethod
    def _target(flow: str) -> str:
        return {"day_one_brief": "Planner", "supplier_overlap": "Researcher", "contract_cliff": "Researcher", "policy_gap": "Researcher",
                "confirm_match": "ApprovalGate", "approve_draft": "ApprovalGate"}.get(flow, "Researcher")

    @staticmethod
    def _parse_confirm(query: str) -> dict[str, Any]:
        """Pull "'A' (Council) is the same supplier as 'B' (Council)" out of free text."""
        out: dict[str, Any] = {"decision": "split" if re.search(r"\b(split|not the same|different)\b", query, re.I) else "same"}
        quoted = re.findall(r"['\"\u2018\u2019\u201c\u201d]([^'\"\u2018\u2019\u201c\u201d]{2,120})['\"\u2018\u2019\u201c\u201d]\s*\(?\s*(Woking|Guildford|Waverley)?", query, re.I)
        if len(quoted) >= 2:
            out["a_name"], a_c = quoted[0][0].strip(), quoted[0][1]
            out["b_name"], b_c = quoted[1][0].strip(), quoted[1][1]
            if a_c:
                out["a_council"] = a_c.capitalize()
            if b_c:
                out["b_council"] = b_c.capitalize()
        return out
