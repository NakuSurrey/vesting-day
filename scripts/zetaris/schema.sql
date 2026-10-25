-- VESTING DAY source schemas: one per council, so Zetaris federates three sources.
-- Run once against the Postgres database that sits next to Zetaris:
--   psql "$VD_PG_DSN" -f scripts/zetaris/schema.sql

CREATE SCHEMA IF NOT EXISTS woking;
CREATE SCHEMA IF NOT EXISTS guildford;
CREATE SCHEMA IF NOT EXISTS waverley;

DO $$
DECLARE s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['woking', 'guildford', 'waverley'] LOOP
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.spend (
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
        source_row integer NOT NULL)', s);
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.contracts (
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
        source_row integer NOT NULL)', s);
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.policy_clause (
        policy_family text NOT NULL,
        council text NOT NULL,
        clause_key text NOT NULL,
        value_text text,
        value_num numeric,
        unit text,
        source_pdf text,
        page integer,
        quote text,
        PRIMARY KEY (policy_family, council, clause_key))', s);
  END LOOP;
END $$;
