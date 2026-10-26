-- Table shape for ONE council database (vd_woking, vd_guildford, vd_waverley).
-- scripts/zetaris/build_load_sql.py runs this inside each of the three databases,
-- so each council is its own separate source for Zetaris to federate.

CREATE TABLE spend (
    provenance_id text PRIMARY KEY,
    council text NOT NULL,
    payment_date date,
    accounting_period text,
    invoice_date date,
    supplier_raw text NOT NULL,
    supplier_ref text,
    amount_gbp numeric(14,2) NOT NULL,
    service_area text,
    expense_type text,
    invoice_ref text,
    source_file text NOT NULL,
    source_row integer NOT NULL
);

CREATE TABLE contracts (
    provenance_id text PRIMARY KEY,
    council text NOT NULL,
    contract_ref text,
    title text,
    supplier_raw text NOT NULL,
    status text,
    start_date date,
    end_date date,
    max_extension_end date,
    annual_value_gbp numeric(14,2),
    total_value_gbp numeric(14,2),
    directorate text,
    supplier_company_number text,
    source_file text NOT NULL,
    source_row integer NOT NULL
);

CREATE TABLE policy_clause (
    policy_family text NOT NULL,
    council text NOT NULL,
    clause_key text NOT NULL,
    value_text text,
    value_num numeric,
    unit text,
    source_pdf text,
    page integer,
    quote text,
    PRIMARY KEY (policy_family, council, clause_key)
);
