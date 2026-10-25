"""ResearcherAgent: asks the data layer questions in SQL and returns rows with provenance.

Live mode runs the same SQL through Zetaris (query-in-place across the three
councils' sources); sample mode runs it over the cached published files. The
agent does not know which - it only knows the data layer's name for the trace.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.agents.base import Agent


def _in_list(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


class ResearcherAgent(Agent):
    name = "Researcher"
    role = "Runs federated SQL against the data layer (Zetaris live, cached council files in sample mode) and returns rows with provenance"

    def _run(self, question: str, sql: str, limit: int = 5000) -> list[dict[str, Any]]:
        rows = self.ctx.data.run_sql(sql, limit=limit)
        self.trace(
            "query_data_layer",
            f"{question} | SQL: {' '.join(sql.split())[:220]}",
            f"{len(rows)} rows from {self.ctx.data.name}",
            target_agent=None,
            confidence=1.0,
            data_layer=self.ctx.data.name,
        )
        return rows

    # --- spend -----------------------------------------------------------

    def supplier_spend(self, councils: list[str]) -> list[dict[str, Any]]:
        sql = f"""
            SELECT council, supplier_raw, COUNT(*) AS n_payments, ROUND(SUM(amount_gbp), 2) AS total_gbp,
                   MIN(payment_date) AS first_payment, MAX(payment_date) AS last_payment,
                   MIN(accounting_period) AS first_period, MAX(accounting_period) AS last_period,
                   MIN(provenance_id) AS example_provenance, MIN(source_file) AS source_file
            FROM {{spend}}
            WHERE council IN ({_in_list(councils)})
            GROUP BY council, supplier_raw
        """
        return self._run(f"spend per supplier for {', '.join(councils)}", sql, limit=20000)

    def council_windows(self, councils: list[str]) -> list[dict[str, Any]]:
        sql = f"""
            SELECT council, COUNT(*) AS rows_published, ROUND(SUM(amount_gbp), 2) AS total_gbp,
                   MIN(payment_date) AS payment_from, MAX(payment_date) AS payment_to,
                   MIN(accounting_period) AS period_from, MAX(accounting_period) AS period_to,
                   COUNT(DISTINCT supplier_raw) AS distinct_suppliers
            FROM {{spend}}
            WHERE council IN ({_in_list(councils)})
            GROUP BY council
        """
        return self._run("per-council publication window", sql)

    def supplier_rows(self, council: str, supplier_raw: str, limit: int = 5) -> list[dict[str, Any]]:
        sql = f"""
            SELECT provenance_id, payment_date, accounting_period, amount_gbp, service_area, expense_type, source_file, source_row
            FROM {{spend}}
            WHERE council = '{council.replace("'", "''")}' AND supplier_raw = '{supplier_raw.replace("'", "''")}'
            ORDER BY amount_gbp DESC
        """
        return self._run(f"evidence rows for {supplier_raw} ({council})", sql, limit=limit)

    # --- contracts --------------------------------------------------------

    def contracts_near(self, councils: list[str], vesting_day: str, window_days: int) -> list[dict[str, Any]]:
        vd = date.fromisoformat(vesting_day)
        lo, hi = (vd - timedelta(days=window_days)).isoformat(), (vd + timedelta(days=window_days)).isoformat()
        sql = f"""
            SELECT provenance_id, council, contract_ref, title, supplier_raw, status, start_date, end_date,
                   max_extension_end, annual_value_gbp, total_value_gbp, directorate, supplier_company_number, source_file, source_row
            FROM {{contracts}}
            WHERE council IN ({_in_list(councils)})
              AND end_date IS NOT NULL AND end_date >= '{lo}' AND end_date <= '{hi}'
            ORDER BY end_date, council
        """
        return self._run(f"contracts ending within {window_days} days of {vesting_day}", sql)

    def contracts_without_end_date(self, councils: list[str]) -> list[dict[str, Any]]:
        sql = f"""
            SELECT provenance_id, council, contract_ref, title, supplier_raw, start_date, end_date, max_extension_end, source_file, source_row
            FROM {{contracts}}
            WHERE council IN ({_in_list(councils)}) AND (end_date IS NULL OR end_date = '')
        """
        return self._run("contracts with no usable end date", sql)

    def contracts_summary(self, councils: list[str]) -> list[dict[str, Any]]:
        sql = f"""
            SELECT council, COUNT(*) AS contracts, SUM(CASE WHEN end_date IS NULL OR end_date = '' THEN 1 ELSE 0 END) AS no_end_date,
                   MIN(end_date) AS earliest_end, MAX(end_date) AS latest_end
            FROM {{contracts}} WHERE council IN ({_in_list(councils)}) GROUP BY council
        """
        return self._run("contracts register summary", sql)

    # --- policy ------------------------------------------------------------

    def policy_clauses(self, councils: list[str], family: str = "council_tax_support") -> list[dict[str, Any]]:
        sql = f"""
            SELECT policy_family, council, clause_key, value_text, value_num, unit, source_pdf, page, quote
            FROM {{policy_clause}}
            WHERE policy_family = '{family}' AND council IN ({_in_list(councils)})
            ORDER BY clause_key, council
        """
        return self._run(f"{family} clauses for {', '.join(councils)}", sql)
