"""Build the canonical data layer from the councils' raw published files.

Input:  data/raw/<council>/...   (the files exactly as published; see data/raw/MANIFEST.md)
Output: data/sample/spend.csv, contracts.csv, sources.json   (+ counts printed)

Every output row keeps a provenance id (council:file:row) so any number shown by
the agent can be traced to the published file and line it came from.

Rules applied (no personal data):
- rows whose payee looks like a natural person are dropped (title-prefixed names,
  "redacted" placeholders, and first-name + surname patterns)
- the Woking "AccountHolder" column (names of council card holders) is never copied
- nothing is invented; the three councils are mapped to one schema, that is all

Run:  uv run --group prep python scripts/build_sample_data.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("openpyxl is needed: uv sync --group prep")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "sample"

SPEND_COLUMNS = [
    "provenance_id", "council", "payment_date", "accounting_period", "invoice_date",
    "supplier_raw", "supplier_ref", "amount_gbp", "service_area", "expense_type",
    "invoice_ref", "source_file", "source_row",
]
CONTRACT_COLUMNS = [
    "provenance_id", "council", "contract_ref", "title", "supplier_raw", "status",
    "start_date", "end_date", "max_extension_end", "annual_value_gbp", "total_value_gbp",
    "directorate", "supplier_company_number", "source_file", "source_row",
]

# --- helpers ---------------------------------------------------------------

def parse_date(s: object) -> str:
    """Return ISO date or '' for the many date spellings the councils use."""
    if s is None:
        return ""
    if isinstance(s, datetime):
        return s.date().isoformat()
    if isinstance(s, date):
        return s.isoformat()
    txt = str(s).strip()
    if not txt or txt.upper() in ("TO BE DISCUSSED", "TBC", "N/A", "NONE"):
        return ""
    txt = txt.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(txt, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def parse_amount(s: object) -> str:
    if s is None:
        return ""
    txt = str(s).strip().replace("\u00a3", "").replace("\ufffd", "").replace(",", "")
    if txt.startswith("(") and txt.endswith(")"):
        txt = "-" + txt[1:-1]
    try:
        return f"{float(txt):.2f}"
    except ValueError:
        return ""


def read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a CSV (any encoding the councils use) or the first sheet of an XLSX.
    Returns (header, body) with the header found as the first row with >= 5 cells."""
    if path.suffix.lower() == ".csv":
        data = path.read_bytes()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    else:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append([("" if c is None else (c if isinstance(c, (datetime, date)) else str(c).strip())) for c in r])
    hi = next(i for i, r in enumerate(rows) if sum(1 for c in r if str(c).strip()) >= 5)
    header = [str(c).strip() for c in rows[hi]]
    body = [r for r in rows[hi + 1:] if any(str(c).strip() for c in r)]
    return header, body


def col(header: list[str], *names: str) -> int | None:
    low = [h.lower() for h in header]
    for n in names:
        if n.lower() in low:
            return low.index(n.lower())
    return None


# --- natural-person filter ----------------------

TITLE_RE = re.compile(r"^(mr|mrs|ms|miss|dr|rev|mr\.|mrs\.|ms\.|dr\.)\b", re.IGNORECASE)
REDACTED_RE = re.compile(r"\b(redacted|name withheld|personal data|private individual|individual)\b", re.IGNORECASE)
CORPORATE_RE = re.compile(
    r"\b(ltd|limited|plc|llp|cic|inc|co|council|trust|nhs|university|services?|solutions|group|associates|"
    r"partners(hip)?|consult\w*|construction|supplies|holdings|uk|sons|school|charity|association|society|"
    r"borough|county|district|parish|housing|bank|insurance|systems|technolog\w*|engineering|contract\w*|"
    r"management|international|centre|center|club|foundation|federation|agency|leisure|water|energy|power|"
    r"recruitment|utilities|barristers|chambers|solicitors|appliances|specialists|lettings|apartments|"
    r"registry|fleet|platforms|employers|action|direct|online|network\w*|digital|software|detectives|"
    r"arboriculture|lubricants|union|house|estates?|homes?|supply|store|shop|company|enterprises?|"
    r"t/a|trading|architects?|building|photography|storage|connect|ecom|chambers|surveyors?|electrical|"
    r"plumbing|joinery|roofing|flooring|decorators?|cleaning|landscap\w*|garden\w*|catering|designs?|"
    r"studios?|pharmacy|opticians?|dental|vets?|garage|motors?|taxis?|coaches|removals|couriers?|"
    r"woking|guildford|waverley|farnham|godalming|cranleigh|haslemere|byfleet|knaphill|surrey)\b",
    re.IGNORECASE,
)
# Common UK first names (lowercase). Used only to decide that a two-word name with no
# corporate token is a person, not a company. Deliberately conservative.
FIRST_NAMES = set("""
aaron abdul abigail adam adrian aiden alan albert alex alexander alexandra alfie alice alison amanda amber amelia amy andrea
andrew angela ann anna anne annie anthony antony archie arthur ashley barbara barry ben benjamin bernard beth bethany
beverley bill billy bob bobby bradley brandon brenda brian bruce callum cameron carl carol caroline catherine
charles charlie charlotte chloe chris christian christine christopher claire clare clive colin connor craig dale
damian daniel danielle danny darren dave david dawn dean deborah debra declan denis dennis derek diane dominic
donald donna dorothy douglas duncan dylan edward eileen elaine eleanor elizabeth ella ellie emily emma eric erin
ethan eva evelyn ewan faith fiona florence francis frank fred freddie gareth gary gavin gemma geoffrey george
georgia georgina gerald gillian glen glenn gordon grace graham grant greg gregory hannah harriet harry harvey
hayley hazel heather helen henry holly howard hugh ian imogen irene isaac isabel isabella isla jack jackie jacob
jade jake james jamie jane janet janice jasmine jason jay jean jeffrey jennifer jenny jeremy jessica jill jim joan
joanna joanne jodie joe joel john jonathan jordan joseph josephine josh joshua joyce judith julia julian julie
june justin karen kate katherine kathleen kathryn katie kayleigh keith kelly kenneth kevin khalid kieran kim
kirsty kyle laura lauren lawrence leah lee leon leonard lesley leslie lewis liam lily linda lisa logan lorraine
louis louise lucas lucy luke lydia lynn madison malcolm mandy marcus margaret maria marie marilyn marion mark
martin mary mason matthew maureen max megan melanie melissa michael michelle mike mitchell mohammed mohammad
molly morgan muhammad nancy naomi natalie natasha nathan neil niall nicholas nick nicola nicole nigel noah
norman oliver olivia oscar owen paige pamela pat patricia patrick paul paula pauline peter philip phillip
phoebe poppy rachel ralph ray raymond rebecca reece rhys richard rita rob robert robin roger ronald rosemary
rosie ross roy ruby russell ruth ryan sally sam samantha samuel sandra sara sarah scott sean shannon sharon
shaun sheila shirley simon sophia sophie stacey stanley stephanie stephen steve steven stewart stuart sue
susan suzanne sylvia tanya terence terry theo thomas tim timothy tina toby tom tony tracey tracy trevor
tyler valerie vanessa vera victor victoria vincent wayne wendy william yvonne zac zach zachary zoe
""".split())


def looks_like_person(name: str) -> bool:
    n = name.strip()
    if not n:
        return False
    if REDACTED_RE.search(n):
        return True
    if TITLE_RE.match(n) and not CORPORATE_RE.search(n):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", n)
    if len(words) in (2, 3) and not CORPORATE_RE.search(n) and not re.search(r"[\d&*/@().]", n):
        first = words[0].lower()
        if first in FIRST_NAMES:
            return True
        # initial + surname, e.g. "J SMITH"
        if len(words) == 2 and len(words[0]) == 1:
            return True
    return False


# --- spend mapping ---------------------------------------------------------

def map_woking_spend(path: Path) -> list[dict]:
    header, body = read_rows(path)
    c_pay = col(header, "ClearanceDate")
    c_inv = col(header, "InvoiceDate")
    c_sup = col(header, "SupplierName")
    c_ref = col(header, "SupplierRefNo")
    c_amt = col(header, "Amount")
    c_area = col(header, "DepartmentExpenseArea")
    c_type = col(header, "ExpenseType")
    c_uref = col(header, "UniqueReference")
    out = []
    for i, r in enumerate(body, start=2):
        get = lambda c: (str(r[c]).strip() if c is not None and c < len(r) else "")
        out.append({
            "council": "Woking",
            "payment_date": parse_date(get(c_pay)),
            "accounting_period": "",
            "invoice_date": parse_date(get(c_inv)),
            "supplier_raw": get(c_sup),
            "supplier_ref": get(c_ref),
            "amount_gbp": parse_amount(get(c_amt)),
            "service_area": get(c_area),
            "expense_type": get(c_type),
            "invoice_ref": get(c_uref),
            "source_file": f"woking/{path.name}",
            "source_row": i,
        })
    return out


def map_guildford_spend(path: Path) -> list[dict]:
    header, body = read_rows(path)
    c_pay = col(header, "payment_date")
    c_inv = col(header, "invoice_date")
    c_sup = col(header, "supplier_name")
    c_ref = col(header, "supplier_code")
    c_amt = col(header, "net_amount_by_line_item")
    c_area = col(header, "service_responsible")
    c_type = col(header, "account_desc")
    c_tref = col(header, "transaction_ref")
    c_fy = col(header, "financial_year")
    c_fp = col(header, "financial_period")
    out = []
    for i, r in enumerate(body, start=2):
        get = lambda c: (r[c] if c is not None and c < len(r) else "")
        fy, fp = str(get(c_fy)).strip(), str(get(c_fp)).strip()
        period = f"{fy}-{int(fp):02d}" if fy and fp.isdigit() else ""
        out.append({
            "council": "Guildford",
            "payment_date": parse_date(get(c_pay)),
            "accounting_period": period,
            "invoice_date": parse_date(get(c_inv)),
            "supplier_raw": str(get(c_sup)).strip(),
            "supplier_ref": str(get(c_ref)).strip(),
            "amount_gbp": parse_amount(get(c_amt)),
            "service_area": str(get(c_area)).strip(),
            "expense_type": str(get(c_type)).strip(),
            "invoice_ref": str(get(c_tref)).strip(),
            "source_file": f"guildford/{path.name}",
            "source_row": i,
        })
    return out


def map_waverley_spend(path: Path) -> list[dict]:
    header, body = read_rows(path)
    c_period = col(header, "Period")
    c_inv = col(header, "Inv. Date")
    c_sup = col(header, "Supplier ID(T)")
    c_ref = col(header, "Supplier ID")
    c_amt = col(header, "Amount")
    c_area = col(header, "Cost Centre(T)")
    c_type = col(header, "Account(T)")
    c_cat = col(header, "Cipfa1(T)")
    out = []
    for i, r in enumerate(body, start=3):  # title row + header row precede the data
        get = lambda c: (str(r[c]).strip() if c is not None and c < len(r) else "")
        p = get(c_period)  # YYYYPP, PP = financial period (01 = April)
        period = f"{p[:4]}-{p[4:6]}" if len(p) == 6 and p.isdigit() else p
        out.append({
            "council": "Waverley",
            "payment_date": "",  # not published; Waverley publishes by accounting period
            "accounting_period": period,
            "invoice_date": parse_date(get(c_inv)),
            "supplier_raw": get(c_sup),
            "supplier_ref": get(c_ref),
            "amount_gbp": parse_amount(get(c_amt)),
            "service_area": get(c_area),
            "expense_type": get(c_type) or get(c_cat),
            "invoice_ref": "",
            "source_file": f"waverley/{path.name}",
            "source_row": i,
        })
    return out


# --- contracts mapping -----------------------------------------------------

def map_woking_contracts(path: Path) -> list[dict]:
    header, body = read_rows(path)
    g = lambda r, c: (str(r[c]).strip() if c is not None and c < len(r) else "")
    c = {k: col(header, k) for k in [
        "Reference Number", "Title of Agreement", "Supplier Name", "Contract Status",
        "Contract Start Date", "Contract End Date", "Max Extension End Date",
        "Annual Contract Value (net)", "Total Contract Term Value (net)", "Directorate"]}
    out = []
    for i, r in enumerate(body, start=2):
        out.append({
            "council": "Woking",
            "contract_ref": g(r, c["Reference Number"]),
            "title": g(r, c["Title of Agreement"]),
            "supplier_raw": g(r, c["Supplier Name"]),
            "status": g(r, c["Contract Status"]),
            "start_date": parse_date(g(r, c["Contract Start Date"])),
            "end_date": parse_date(g(r, c["Contract End Date"])),
            "max_extension_end": parse_date(g(r, c["Max Extension End Date"])),
            "annual_value_gbp": parse_amount(g(r, c["Annual Contract Value (net)"])),
            "total_value_gbp": parse_amount(g(r, c["Total Contract Term Value (net)"])),
            "directorate": g(r, c["Directorate"]),
            "supplier_company_number": "",
            "source_file": f"woking/{path.name}",
            "source_row": i,
        })
    return out


def map_shared_service_contracts(path: Path, council: str) -> list[dict]:
    """Guildford and Waverley publish the same register layout (shared procurement service)."""
    header, body = read_rows(path)
    g = lambda r, c: (r[c] if c is not None and c < len(r) else "")
    c = {k: col(header, k) for k in [
        "Contract Number", "Contract Name", "Start Date", "End Date", "Max Extension Date",
        "Directorate", "Supplier Name", "Contract Value", "Supplier Company registration number"]}
    out = []
    for i, r in enumerate(body, start=2):
        out.append({
            "council": council,
            "contract_ref": str(g(r, c["Contract Number"])).strip(),
            "title": str(g(r, c["Contract Name"])).strip(),
            "supplier_raw": str(g(r, c["Supplier Name"])).strip(),
            "status": "",
            "start_date": parse_date(g(r, c["Start Date"])),
            "end_date": parse_date(g(r, c["End Date"])),
            "max_extension_end": parse_date(g(r, c["Max Extension Date"])),
            "annual_value_gbp": "",
            "total_value_gbp": parse_amount(g(r, c["Contract Value"])),
            "directorate": str(g(r, c["Directorate"])).strip(),
            "supplier_company_number": str(g(r, c["Supplier Company registration number"])).strip(),
            "source_file": f"{council.lower()}/{path.name}",
            "source_row": i,
        })
    return out


# --- main --------------------------------------------------------------------

SPEND_FILES = [
    ("woking", map_woking_spend, ["woking_2025_11.csv", "woking_2025_12.xlsx", "woking_2026_01.xlsx",
                                  "woking_2026_02.csv", "woking_2026_03.csv", "woking_2026_04.csv"]),
    ("guildford", map_guildford_spend, ["guildford_2026_Q1.xlsx", "guildford_2026_Q2.xlsx"]),
    ("waverley", map_waverley_spend, ["waverley_over500_q1q2_2026_27.csv"]),
]
CONTRACT_FILES = [
    ("woking", lambda p: map_woking_contracts(p), ["woking_contracts_2026_27_q1.csv"]),
    ("guildford", lambda p: map_shared_service_contracts(p, "Guildford"), ["guildford_contracts_2026_q4.xlsx"]),
    ("waverley", lambda p: map_shared_service_contracts(p, "Waverley"), ["waverley_contracts_fy2526_q4.xlsx"]),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spend: list[dict] = []
    dropped_person = 0
    dropped_bad = 0
    per_file: dict[str, dict] = {}
    for folder, mapper, files in SPEND_FILES:
        for f in files:
            rows = mapper(RAW / folder / f)
            kept = 0
            for row in rows:
                if not row["amount_gbp"] or not row["supplier_raw"]:
                    dropped_bad += 1
                    continue
                if looks_like_person(row["supplier_raw"]):
                    dropped_person += 1
                    continue
                row["provenance_id"] = f"{row['council'][:3].lower()}:{f}:{row['source_row']}"
                spend.append(row)
                kept += 1
            per_file[f"{folder}/{f}"] = {"rows_in": len(rows), "rows_kept": kept}

    contracts: list[dict] = []
    for folder, mapper, files in CONTRACT_FILES:
        for f in files:
            rows = mapper(RAW / folder / f)
            kept = 0
            for row in rows:
                if not row["supplier_raw"] or looks_like_person(row["supplier_raw"]):
                    continue
                row["provenance_id"] = f"{row['council'][:3].lower()}:{f}:{row['source_row']}"
                contracts.append(row)
                kept += 1
            per_file[f"{folder}/{f}"] = {"rows_in": len(rows), "rows_kept": kept}

    with open(OUT / "spend.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SPEND_COLUMNS)
        w.writeheader()
        for row in spend:
            w.writerow({k: row.get(k, "") for k in SPEND_COLUMNS})
    with open(OUT / "contracts.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CONTRACT_COLUMNS)
        w.writeheader()
        for row in contracts:
            w.writerow({k: row.get(k, "") for k in CONTRACT_COLUMNS})

    # Per-council window badges, computed from the data, not typed in.
    def window(council: str) -> dict:
        rows = [r for r in spend if r["council"] == council]
        dates = sorted(r["payment_date"] for r in rows if r["payment_date"])
        periods = sorted({r["accounting_period"] for r in rows if r["accounting_period"]})
        return {
            "rows": len(rows),
            "total_gbp": round(sum(float(r["amount_gbp"]) for r in rows), 2),
            "payment_date_min": dates[0] if dates else None,
            "payment_date_max": dates[-1] if dates else None,
            "accounting_periods": periods,
            "distinct_suppliers": len({r["supplier_raw"].strip().upper() for r in rows}),
        }

    sources = {
        "built_from": "data/raw (files as published by each council; see data/raw/MANIFEST.md)",
        "rules": {
            "natural_person_payees_dropped": dropped_person,
            "rows_dropped_missing_amount_or_supplier": dropped_bad,
            "account_holder_names_never_copied": True,
        },
        "councils": {
            "Woking": {
                "cadence": "monthly", "basis": "payment (clearance) date", "format": "CSV + XLSX",
                "window_label": "Nov 2025 - Apr 2026", **window("Woking"),
            },
            "Guildford": {
                "cadence": "quarterly (financial-year quarters)", "basis": "payment date", "format": "XLSX",
                "window_label": "Apr - Sep 2026 (FY2026/27 Q1-Q2)", **window("Guildford"),
            },
            "Waverley": {
                "cadence": "half-yearly", "basis": "accounting period (payment date not published)", "format": "CSV",
                "window_label": "Apr - Sep 2026 (FY2026/27 periods 1-6)", **window("Waverley"),
            },
        },
        "contracts": {c: len([r for r in contracts if r["council"] == c]) for c in ("Woking", "Guildford", "Waverley")},
        "files": per_file,
        "vesting_day": "2027-04-01",
    }
    (OUT / "sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(sources, indent=2))


if __name__ == "__main__":
    main()
