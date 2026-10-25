"""Build data/sample/policy_clauses.csv from the two published Council Tax Support schemes.

Each clause value was located in the scheme PDF (page number recorded) and is
verified here: the script re-reads the cited page and checks that the quoted
anchor text is present, so a wrong page or a changed PDF fails loudly.

Working-age schemes, 2026:
  Woking    data/raw/woking/woking_cts_scheme_2026.pdf             (164 pages)
  Guildford data/raw/guildford/guildford_ctr_scheme_working_age_2026.pdf (140 pages)

Run:  uv run --group prep python scripts/build_policy_clauses.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDFS = {
    "Woking": ROOT / "data/raw/woking/woking_cts_scheme_2026.pdf",
    "Guildford": ROOT / "data/raw/guildford/guildford_ctr_scheme_working_age_2026.pdf",
}

# (council, clause_key, value_text, value_num, unit, page, anchor text that must appear on that page, quote)
CLAUSES = [
    # capital limit (working age exclusion class)
    ("Woking", "capital_limit_gbp", "10,000", 10000, "GBP", 32, "capital exceeds £10,000",
     "Class of person excluded from this scheme: capital limit 22. (1) The class of person described in this paragraph consists of any person whose capital exceeds £10,000"),
    ("Guildford", "capital_limit_gbp", "6,000", 6000, "GBP", 49, "capital exceeds £6,000",
     "42. Class of person excluded from this scheme: capital limit (1) ... any person whose capital exceeds £6,000"),
    # band cap
    ("Woking", "band_cap", "Band D", None, "band", 36, "capped at a maximum liability of Band D",
     "28B For classes D and E, the maximum Council Tax reduction will be capped at a maximum liability of Band D"),
    ("Guildford", "band_cap", "Band D", None, "band", 51, "council tax band D",
     "subject to (i) a maximum amount that is equal to the council tax charge of a dwelling in council tax band D"),
    # bands excluded from the scheme altogether
    ("Woking", "excluded_bands", "none (bands F-H claim, capped at Band D)", None, "bands", 36, "capped at a maximum liability of Band D",
     "No exclusion by valuation band; the reduction for classes D and E is capped at Band D liability (para 28B)"),
    ("Guildford", "excluded_bands", "F, G and H", None, "bands", 49, "valuation band F, G and H",
     "42A Class of person excluded from this scheme: valuation band F, G and H ... any person whose liability for Council Tax is in respect of a chargeable dwelling which falls within valuation band F, G or H"),
    # maximum support
    ("Woking", "max_support_pct", "100", 100, "% of liability", 35, "100 per cent of the amount A/B",
     "28A (1) ... the amount of a person's maximum Council Tax reduction in respect of a day is 100 per cent of the amount A/B"),
    ("Guildford", "max_support_pct", "100", 100, "% of liability", 51, "100 per cent of the amount A/B",
     "47 (1) ... the amount of a person's maximum council tax reduction in respect of a day is 100 per cent of the amount A/B"),
    # minimum award
    ("Woking", "min_award_gbp_week", "5.00", 5.0, "GBP/week", 107, "less than £5.00 per reduction week",
     "118. Where a reduction is payable, it shall not be payable where the amount to which a person would other be entitled is less than £5.00 per reduction week"),
    ("Guildford", "min_award_gbp_week", "10.00", 10.0, "GBP/week", 55, "less than £10.00 per reduction week",
     "49A. Minimum amount of reduction under this scheme ... it shall not be awarded where the amount to which a person would otherwise be entitled is less than £10.00 per reduction week"),
    # standard earnings disregard, single claimant
    ("Woking", "earnings_disregard_gbp_week", "5 (single), 10 (couple), 25 (lone parent)", 5.0, "GBP/week", 132, "£5 shall be disregarded if an applicant who has no partner has earnings",
     "8. Except where the applicant or his partner qualifies for a £20 disregard ... (a) £5 shall be disregarded if an applicant who has no partner has earnings; (b) £10 shall be disregarded if an applicant who has a partner has earnings"),
    ("Guildford", "earnings_disregard_gbp_week", "5 (single), 10 (couple), 25 (lone parent)", 5.0, "GBP/week", 116, "paragraphs 4 to 10 applies, £5",
     "11. In a case to which none of the paragraphs 4 to 10 applies, £5. (couple £10, lone parent £25 under paragraphs 5 and 8)"),
    # highest non-dependant deduction
    ("Woking", "non_dep_deduction_top_gbp_week", "15.35", 15.35, "GBP/week", 37, "£15.35 x 1/7",
     "29A (1) (a) in respect of a non-dependant aged 18 or over in remunerative work, £15.35 x 1/7; (b) ... £5.00 x 1/7 (income bands £279 / £485 / £605)"),
    ("Guildford", "non_dep_deduction_top_gbp_week", "15.35", 15.35, "GBP/week", 52, "£15.35 x 1/7",
     "48 (1) (a) in respect of a non-dependant aged 18 or over in remunerative work, £15.35 x 1/7; (b) ... £5.00 x 1/7 (income bands £266 / £463 / £577)"),
    # backdating
    ("Woking", "backdating_weeks", "26 (6 months, with continuous good cause)", 26, "weeks", 102, "6 months before the date the application was made",
     "111 (2) That date is the latest of (a) the first day from which the applicant had continuous good cause; (b) the day 6 months before the date the application was made"),
    ("Guildford", "backdating_weeks", "4 (one calendar month, with continuous good cause)", 4, "weeks", 100, "one calendar month before the date the application was made",
     "106 (2) That date is the latest of (a) the first day from which the applicant had continuous good cause; (b) the day one calendar month before the date the application was made"),
    # second adult rebate for working age
    ("Woking", "second_adult_rebate", "not available to working age (pensioners only, Class C)", 0, "yes/no", 28, "Class D: persons who are not pensioners",
     "Working-age classes are D and E only (page 28); the alternative maximum Council Tax reduction (second adult rebate) is defined for pensioners, Class C, paragraph 15"),
    ("Guildford", "second_adult_rebate", "not available to working age (Class F not used)", 0, "yes/no", 45, "Class F - Not used",
     "Class F - Not used"),
]

FIELDS = ["policy_family", "council", "clause_key", "value_text", "value_num", "unit", "source_pdf", "page", "quote"]


def main() -> None:
    readers = {c: PdfReader(p) for c, p in PDFS.items()}
    out = ROOT / "data/sample/policy_clauses.csv"
    rows = []
    problems = 0
    for council, key, text, num, unit, page, anchor, quote in CLAUSES:
        page_text = " ".join((readers[council].pages[page - 1].extract_text() or "").split())
        norm = lambda s: re.sub(r"\s+", " ", s.replace("’", "'")).strip()
        if norm(anchor) not in norm(page_text):
            problems += 1
            print(f"NOT FOUND on page {page} of {council}: {anchor!r}", file=sys.stderr)
        rows.append({
            "policy_family": "council_tax_support", "council": council, "clause_key": key, "value_text": text,
            "value_num": "" if num is None else num, "unit": unit,
            "source_pdf": str(PDFS[council].relative_to(ROOT)), "page": page, "quote": quote,
        })
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} clause rows to {out}; anchors verified against the PDFs: {len(rows) - problems}/{len(rows)}")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
