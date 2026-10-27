"""Supplier name matching - the Resolver's pure logic, testable on its own.

Thresholds (locked in the plan):
  exact after normalisation            -> 0.95  method "exact"
  token-sort similarity >= 0.92        -> 0.85 if Companies House agrees, else 0.80 and needs a human
  0.70 <= similarity < 0.92            -> candidate for the match judge (live) or a human (sample)
  < 0.70                               -> no match
Nothing turns "confirmed" without a human; see the ApprovalGate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Optional

EXACT = 0.95
HIGH = 0.92
BAND_LOW = 0.70

_DROP_TOKENS = {
    "LTD", "LIMITED", "PLC", "LLP", "CO", "COMPANY", "THE", "UK", "INC", "CORP", "CORPORATION",
    "GB", "ENGLAND", "GROUP", "HOLDINGS", "CIS",
}
_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_WS = re.compile(r"\s+")


def normalise(name: str) -> str:
    s = name.upper().replace("&", " AND ")
    s = re.sub(r"\bT/A\b.*$", "", s)              # trading-as suffix
    s = _PUNCT.sub(" ", s)
    toks = [t for t in _WS.split(s) if t and t not in _DROP_TOKENS]
    return " ".join(toks)


def tokens(name: str) -> list[str]:
    return normalise(name).split()


_GENERIC = {
    "BOROUGH", "COUNCIL", "DISTRICT", "COUNTY", "SERVICES", "SERVICE", "SOLUTIONS", "CONSULTANCY", "CONSULTING",
    "CONSULTANTS", "CONSTRUCTION", "CONTRACTORS", "CONTRACTING", "ENGINEERING", "ENGINEERS", "MANAGEMENT",
    "ASSOCIATES", "PARTNERS", "PARTNERSHIP", "RECRUITMENT", "RESOURCING", "SOUTH", "EAST", "WEST", "NORTH",
    "SOUTHEAST", "SOUTHERN", "LONDON", "SURREY", "ENERGY", "ENVIRONMENTAL", "HOUSING", "ASSOCIATION", "TRUST",
    "FIRE", "SECURITY", "AND", "OF", "FOR", "CLIENT", "ACCOUNT", "LEGAL", "LAW", "SOLICITORS", "BARRISTERS",
    "CHAMBERS", "CARE", "HEALTH", "CENTRE", "SUPPLIES", "PRODUCTS", "SYSTEMS", "TECHNOLOGY", "TECHNOLOGIES",
    "SOFTWARE", "DIGITAL", "DATA", "MEDIA", "DESIGN", "PRINT", "PROPERTY", "ESTATES", "HOMES", "BUILDING",
    "BUILDERS", "LANDSCAPES", "LANDSCAPING", "CLEANING", "CATERING", "TRAINING", "EDUCATION", "SCHOOL",
    "COMMUNITY", "FOUNDATION", "CHARITY", "INTERNATIONAL", "NATIONAL", "GLOBAL", "EUROPE", "EUROPEAN",
    "MUNICIPAL", "ARCHITECTURAL", "COATINGS", "DECORATORS", "LIMITED", "LLP", "PLC", "INSURANCE", "FINANCE",
}
_PUBLIC = {"COUNCIL", "NHS", "HMRC", "HM", "GOVERNMENT", "DEPARTMENT", "MINISTRY", "POLICE", "FIRE", "AMBULANCE",
           "UNIVERSITY", "COLLEGE", "ACADEMY", "SCHOOL", "PARISH", "TOWN", "CROWN", "COURT", "REGISTRY", "AGENCY"}


def distinctive_tokens(name: str) -> set[str]:
    """Tokens that actually identify an organisation (generic trade words removed)."""
    return {t for t in tokens(name) if t not in _GENERIC and len(t) > 1}


def is_public_body(name: str) -> bool:
    return bool(set(tokens(name)) & _PUBLIC)


def similarity(a: str, b: str) -> float:
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    plain = SequenceMatcher(None, na, nb).ratio()
    sa, sb = " ".join(sorted(na.split())), " ".join(sorted(nb.split()))
    sorted_ratio = SequenceMatcher(None, sa, sb).ratio()
    return max(plain, sorted_ratio)


@dataclass
class Candidate:
    a_council: str
    a_name: str
    b_council: str
    b_name: str
    similarity: float
    method: str                 # exact | fuzzy-high | fuzzy-band
    score: float                # the locked score for the method
    status: str = "pending"     # auto | pending | needs-human | unlikely | confirmed | split
    decision_id: Optional[str] = None
    companies_house: Optional[dict] = None
    notes: list[str] = field(default_factory=list)
    model_verdict: Optional[str] = None   # SAME | DIFFERENT | UNSURE - the match judge's hint; never a status

    @property
    def key(self) -> str:
        return pair_key(self.a_council, self.a_name, self.b_council, self.b_name)


def pair_key(a_council: str, a_name: str, b_council: str, b_name: str) -> str:
    left = f"{a_council}:{normalise(a_name)}"
    right = f"{b_council}:{normalise(b_name)}"
    return " <> ".join(sorted([left, right]))


def _blocks(names: Iterable[str]) -> dict[str, list[str]]:
    """Blocking keys, so not every pair is compared: first token and 4-char prefix."""
    out: dict[str, list[str]] = {}
    for n in names:
        toks = tokens(n)
        if not toks:
            continue
        keys = {toks[0], normalise(n)[:4]}
        for t in toks:
            if len(t) >= 5:
                keys.add(t)
        for k in keys:
            out.setdefault(k, []).append(n)
    return out


def find_candidates(
    names_by_council: dict[str, Iterable[str]],
    councils: Optional[list[str]] = None,
) -> list[Candidate]:
    """Compare supplier names across every pair of councils and return scored candidates."""
    cs = councils or sorted(names_by_council)
    blocks = {c: _blocks(names_by_council[c]) for c in cs}
    seen: set[str] = set()
    out: list[Candidate] = []
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            ca, cb = cs[i], cs[j]
            for key, a_names in blocks[ca].items():
                b_names = blocks[cb].get(key)
                if not b_names:
                    continue
                for a in a_names:
                    for b in b_names:
                        k = pair_key(ca, a, cb, b)
                        if k in seen:
                            continue
                        sim = similarity(a, b)
                        if sim < BAND_LOW:
                            continue
                        seen.add(k)
                        if sim >= 0.999:
                            out.append(Candidate(ca, a, cb, b, round(sim, 4), "exact", EXACT, status="auto"))
                        elif sim >= HIGH:
                            out.append(Candidate(ca, a, cb, b, round(sim, 4), "fuzzy-high", 0.80, status="pending"))
                        else:
                            out.append(Candidate(ca, a, cb, b, round(sim, 4), "fuzzy-band", round(sim, 2), status="pending"))
    out.sort(key=lambda c: (-c.score, -c.similarity, c.key))
    return out
