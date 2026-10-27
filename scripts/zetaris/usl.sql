-- VESTING DAY - Zetaris Unified Semantic Layer (USL) "west_surrey"
--
-- One semantic model over the three council sources registered in register_sources.sql
-- (woking_pg, guildford_pg, waverley_pg). Each council stays its own database; the USL
-- only describes and binds them, it copies nothing.
--
-- Run it with:  uv run python scripts/zetaris/build_usl.py
-- The runner sends each block below as ONE request to the Zetaris REST API, in order, and
-- writes what Zetaris returned to docs/ZETARIS_USL_EVIDENCE.md and logs/zetaris-usl-build.jsonl.
-- (The SQL Workspace splits editor text at every ';', so the COMPILE block must not be pasted
-- there in pieces; use the runner, or Unified Semantic Layer -> New USL in the UI.)
--
-- Each block starts with a line:  -- @step <kind> <name>
--   explore = exploratory query on one source   build = namespace, compile, activate
--   check   = inspect the deployed model         query = query the activated USL
--   repro   = reproduce a Zetaris behaviour I found (a different answer is the expected result)
--   dq      = data-quality rules and their results

-- @step explore woking_spend_profile
SELECT COUNT(*) AS payments, ROUND(SUM(amount_gbp), 2) AS total_gbp,
       MIN(payment_date) AS first_payment, MAX(payment_date) AS last_payment,
       MIN(accounting_period) AS first_period, MAX(accounting_period) AS last_period
FROM woking_pg.spend

-- @step explore woking_contracts_profile
SELECT COUNT(*) AS contracts,
       SUM(CASE WHEN end_date IS NULL THEN 1 ELSE 0 END) AS no_end_date,
       SUM(CASE WHEN max_extension_end IS NOT NULL THEN 1 ELSE 0 END) AS extension_date_recorded,
       MIN(end_date) AS earliest_end, MAX(end_date) AS latest_end
FROM woking_pg.contracts

-- @step explore woking_top_suppliers
SELECT supplier_raw, COUNT(*) AS payments, ROUND(SUM(amount_gbp), 2) AS total_gbp
FROM woking_pg.spend
GROUP BY supplier_raw
ORDER BY total_gbp DESC
LIMIT 5

-- @step explore guildford_spend_profile
SELECT COUNT(*) AS payments, ROUND(SUM(amount_gbp), 2) AS total_gbp,
       MIN(payment_date) AS first_payment, MAX(payment_date) AS last_payment,
       MIN(accounting_period) AS first_period, MAX(accounting_period) AS last_period
FROM guildford_pg.spend

-- @step explore guildford_contracts_profile
SELECT COUNT(*) AS contracts,
       SUM(CASE WHEN end_date IS NULL THEN 1 ELSE 0 END) AS no_end_date,
       SUM(CASE WHEN max_extension_end IS NOT NULL THEN 1 ELSE 0 END) AS extension_date_recorded,
       MIN(end_date) AS earliest_end, MAX(end_date) AS latest_end
FROM guildford_pg.contracts

-- @step explore guildford_top_suppliers
SELECT supplier_raw, COUNT(*) AS payments, ROUND(SUM(amount_gbp), 2) AS total_gbp
FROM guildford_pg.spend
GROUP BY supplier_raw
ORDER BY total_gbp DESC
LIMIT 5

-- @step explore waverley_spend_profile
SELECT COUNT(*) AS payments, ROUND(SUM(amount_gbp), 2) AS total_gbp,
       MIN(payment_date) AS first_payment, MAX(payment_date) AS last_payment,
       MIN(accounting_period) AS first_period, MAX(accounting_period) AS last_period
FROM waverley_pg.spend

-- @step explore waverley_contracts_profile
SELECT COUNT(*) AS contracts,
       SUM(CASE WHEN end_date IS NULL THEN 1 ELSE 0 END) AS no_end_date,
       SUM(CASE WHEN max_extension_end IS NOT NULL THEN 1 ELSE 0 END) AS extension_date_recorded,
       MIN(end_date) AS earliest_end, MAX(end_date) AS latest_end
FROM waverley_pg.contracts

-- @step explore waverley_top_suppliers
SELECT supplier_raw, COUNT(*) AS payments, ROUND(SUM(amount_gbp), 2) AS total_gbp
FROM waverley_pg.spend
GROUP BY supplier_raw
ORDER BY total_gbp DESC
LIMIT 5

-- @step build parent_namespace
-- On an instance with no USL yet, lightning.metastore itself does not exist and creating a
-- namespace under it fails with "parent namespace : metastore is not existing" (seen on my
-- first run, and noted in Zetaris's getting-started companion guide, section 8.4).
CREATE NAMESPACE IF NOT EXISTS lightning.metastore

-- @step build namespace
CREATE NAMESPACE IF NOT EXISTS lightning.metastore.vesting_day

-- @step build compile
COMPILE USL IF NOT EXISTS west_surrey DEPLOY NAMESPACE lightning.metastore.vesting_day DDL
CREATE TABLE council (
  council        varchar(20) NOT NULL PRIMARY KEY,
  zetaris_source varchar(30) NOT NULL
);
CREATE TABLE spend (
  provenance_id     varchar(100) NOT NULL PRIMARY KEY,
  council           varchar(20) NOT NULL FOREIGN KEY REFERENCES council(council),
  payment_date      date,
  accounting_period varchar(20),
  invoice_date      date,
  supplier_raw      varchar(300) NOT NULL,
  supplier_ref      varchar(60),
  amount_gbp        decimal(14,2) NOT NULL,
  service_area      varchar(200),
  expense_type      varchar(200),
  invoice_ref       varchar(60),
  source_file       varchar(120) NOT NULL,
  source_row        integer NOT NULL
);
CREATE TABLE contracts (
  provenance_id           varchar(100) NOT NULL PRIMARY KEY,
  council                 varchar(20) NOT NULL FOREIGN KEY REFERENCES council(council),
  contract_ref            varchar(60),
  title                   varchar(500),
  supplier_raw            varchar(300) NOT NULL,
  status                  varchar(40),
  start_date              date,
  end_date                date,
  max_extension_end       date,
  annual_value_gbp        decimal(14,2),
  total_value_gbp         decimal(14,2),
  directorate             varchar(120),
  supplier_company_number varchar(20),
  source_file             varchar(120) NOT NULL,
  source_row              integer NOT NULL
);
CREATE TABLE policy_clause (
  clause_id     varchar(200) NOT NULL PRIMARY KEY,
  policy_family varchar(60) NOT NULL,
  council       varchar(20) NOT NULL FOREIGN KEY REFERENCES council(council),
  clause_key    varchar(80) NOT NULL,
  value_text    varchar(200),
  value_num     double,
  unit          varchar(40),
  source_pdf    varchar(200),
  page          integer,
  quote         varchar(1000)
)

-- @step build activate_council
ACTIVATE USL TABLE lightning.metastore.vesting_day.west_surrey.council AS
SELECT COALESCE(MAX(council), '') AS council, 'woking_pg' AS zetaris_source FROM woking_pg.spend
UNION ALL
SELECT COALESCE(MAX(council), '') AS council, 'guildford_pg' AS zetaris_source FROM guildford_pg.spend
UNION ALL
SELECT COALESCE(MAX(council), '') AS council, 'waverley_pg' AS zetaris_source FROM waverley_pg.spend

-- @step build activate_spend
ACTIVATE USL TABLE lightning.metastore.vesting_day.west_surrey.spend AS
SELECT COALESCE(provenance_id, '') AS provenance_id,
       COALESCE(council, '') AS council,
       CAST(payment_date AS DATE) AS payment_date,
       accounting_period AS accounting_period,
       CAST(invoice_date AS DATE) AS invoice_date,
       COALESCE(supplier_raw, '') AS supplier_raw,
       supplier_ref AS supplier_ref,
       COALESCE(CAST(amount_gbp AS DECIMAL(14,2)), CAST(0 AS DECIMAL(14,2))) AS amount_gbp,
       service_area AS service_area,
       expense_type AS expense_type,
       invoice_ref AS invoice_ref,
       COALESCE(source_file, '') AS source_file,
       COALESCE(CAST(source_row AS INT), 0) AS source_row
FROM woking_pg.spend
UNION ALL
SELECT COALESCE(provenance_id, '') AS provenance_id,
       COALESCE(council, '') AS council,
       CAST(payment_date AS DATE) AS payment_date,
       accounting_period AS accounting_period,
       CAST(invoice_date AS DATE) AS invoice_date,
       COALESCE(supplier_raw, '') AS supplier_raw,
       supplier_ref AS supplier_ref,
       COALESCE(CAST(amount_gbp AS DECIMAL(14,2)), CAST(0 AS DECIMAL(14,2))) AS amount_gbp,
       service_area AS service_area,
       expense_type AS expense_type,
       invoice_ref AS invoice_ref,
       COALESCE(source_file, '') AS source_file,
       COALESCE(CAST(source_row AS INT), 0) AS source_row
FROM guildford_pg.spend
UNION ALL
SELECT COALESCE(provenance_id, '') AS provenance_id,
       COALESCE(council, '') AS council,
       CAST(payment_date AS DATE) AS payment_date,
       accounting_period AS accounting_period,
       CAST(invoice_date AS DATE) AS invoice_date,
       COALESCE(supplier_raw, '') AS supplier_raw,
       supplier_ref AS supplier_ref,
       COALESCE(CAST(amount_gbp AS DECIMAL(14,2)), CAST(0 AS DECIMAL(14,2))) AS amount_gbp,
       service_area AS service_area,
       expense_type AS expense_type,
       invoice_ref AS invoice_ref,
       COALESCE(source_file, '') AS source_file,
       COALESCE(CAST(source_row AS INT), 0) AS source_row
FROM waverley_pg.spend

-- @step build activate_contracts
ACTIVATE USL TABLE lightning.metastore.vesting_day.west_surrey.contracts AS
SELECT COALESCE(provenance_id, '') AS provenance_id,
       COALESCE(council, '') AS council,
       contract_ref AS contract_ref,
       title AS title,
       COALESCE(supplier_raw, '') AS supplier_raw,
       status AS status,
       CAST(start_date AS DATE) AS start_date,
       CAST(end_date AS DATE) AS end_date,
       CAST(max_extension_end AS DATE) AS max_extension_end,
       CAST(annual_value_gbp AS DECIMAL(14,2)) AS annual_value_gbp,
       CAST(total_value_gbp AS DECIMAL(14,2)) AS total_value_gbp,
       directorate AS directorate,
       supplier_company_number AS supplier_company_number,
       COALESCE(source_file, '') AS source_file,
       COALESCE(CAST(source_row AS INT), 0) AS source_row
FROM woking_pg.contracts
UNION ALL
SELECT COALESCE(provenance_id, '') AS provenance_id,
       COALESCE(council, '') AS council,
       contract_ref AS contract_ref,
       title AS title,
       COALESCE(supplier_raw, '') AS supplier_raw,
       status AS status,
       CAST(start_date AS DATE) AS start_date,
       CAST(end_date AS DATE) AS end_date,
       CAST(max_extension_end AS DATE) AS max_extension_end,
       CAST(annual_value_gbp AS DECIMAL(14,2)) AS annual_value_gbp,
       CAST(total_value_gbp AS DECIMAL(14,2)) AS total_value_gbp,
       directorate AS directorate,
       supplier_company_number AS supplier_company_number,
       COALESCE(source_file, '') AS source_file,
       COALESCE(CAST(source_row AS INT), 0) AS source_row
FROM guildford_pg.contracts
UNION ALL
SELECT COALESCE(provenance_id, '') AS provenance_id,
       COALESCE(council, '') AS council,
       contract_ref AS contract_ref,
       title AS title,
       COALESCE(supplier_raw, '') AS supplier_raw,
       status AS status,
       CAST(start_date AS DATE) AS start_date,
       CAST(end_date AS DATE) AS end_date,
       CAST(max_extension_end AS DATE) AS max_extension_end,
       CAST(annual_value_gbp AS DECIMAL(14,2)) AS annual_value_gbp,
       CAST(total_value_gbp AS DECIMAL(14,2)) AS total_value_gbp,
       directorate AS directorate,
       supplier_company_number AS supplier_company_number,
       COALESCE(source_file, '') AS source_file,
       COALESCE(CAST(source_row AS INT), 0) AS source_row
FROM waverley_pg.contracts

-- @step build activate_policy_clause
ACTIVATE USL TABLE lightning.metastore.vesting_day.west_surrey.policy_clause AS
SELECT COALESCE(CONCAT(policy_family, '|', council, '|', clause_key), '') AS clause_id,
       COALESCE(policy_family, '') AS policy_family,
       COALESCE(council, '') AS council,
       COALESCE(clause_key, '') AS clause_key,
       value_text AS value_text,
       CAST(value_num AS DOUBLE) AS value_num,
       unit AS unit,
       source_pdf AS source_pdf,
       CAST(page AS INT) AS page,
       quote AS quote
FROM woking_pg.policy_clause
UNION ALL
SELECT COALESCE(CONCAT(policy_family, '|', council, '|', clause_key), '') AS clause_id,
       COALESCE(policy_family, '') AS policy_family,
       COALESCE(council, '') AS council,
       COALESCE(clause_key, '') AS clause_key,
       value_text AS value_text,
       CAST(value_num AS DOUBLE) AS value_num,
       unit AS unit,
       source_pdf AS source_pdf,
       CAST(page AS INT) AS page,
       quote AS quote
FROM guildford_pg.policy_clause
UNION ALL
SELECT COALESCE(CONCAT(policy_family, '|', council, '|', clause_key), '') AS clause_id,
       COALESCE(policy_family, '') AS policy_family,
       COALESCE(council, '') AS council,
       COALESCE(clause_key, '') AS clause_key,
       value_text AS value_text,
       CAST(value_num AS DOUBLE) AS value_num,
       unit AS unit,
       source_pdf AS source_pdf,
       CAST(page AS INT) AS page,
       quote AS quote
FROM waverley_pg.policy_clause

-- @step check tables_and_activation
SHOW NAMESPACES OR TABLES IN lightning.metastore.vesting_day

-- @step query usl_payments_per_council
SELECT s.council, k.zetaris_source, COUNT(*) AS payments, ROUND(SUM(s.amount_gbp), 2) AS total_gbp
FROM lightning.metastore.vesting_day.west_surrey.spend s
JOIN lightning.metastore.vesting_day.west_surrey.council k ON s.council = k.council
GROUP BY s.council, k.zetaris_source
ORDER BY s.council

-- @step query usl_contract_cliff
-- 180 days either side of vesting day (2027-04-01); no extension date recorded past it.
-- The agent's contract-cliff flow applies the same rule. Written with CASE, not
-- "AND (x IS NULL OR x <= ...)": see the two repro steps below.
SELECT c.council, k.zetaris_source, COUNT(*) AS hard_cliff_contracts,
       ROUND(SUM(COALESCE(NULLIF(c.total_value_gbp, 0), c.annual_value_gbp, 0)), 2) AS stated_value_gbp
FROM lightning.metastore.vesting_day.west_surrey.contracts c
JOIN lightning.metastore.vesting_day.west_surrey.council k ON c.council = k.council
WHERE c.end_date >= '2026-10-03' AND c.end_date <= '2027-09-28'
  AND CASE WHEN c.max_extension_end IS NULL THEN 1
           WHEN c.max_extension_end <= '2027-04-01' THEN 1
           ELSE 0 END = 1
GROUP BY c.council, k.zetaris_source
ORDER BY c.council

-- @step query usl_supplier_names_in_two_or_more_councils
-- Exact names only (case and outer spaces ignored). The agent's Resolver goes further:
-- it normalises names and compares them in pairs, and only a person confirms a near match.
SELECT COUNT(*) AS supplier_names
FROM (SELECT UPPER(TRIM(supplier_raw)) AS supplier_name
      FROM lightning.metastore.vesting_day.west_surrey.spend
      GROUP BY UPPER(TRIM(supplier_raw))
      HAVING COUNT(DISTINCT council) >= 2) x

-- @step query usl_top_shared_supplier_names
SELECT UPPER(TRIM(supplier_raw)) AS supplier_name, COUNT(DISTINCT council) AS councils,
       ROUND(SUM(amount_gbp), 2) AS combined_spend_gbp
FROM lightning.metastore.vesting_day.west_surrey.spend
GROUP BY UPPER(TRIM(supplier_raw))
HAVING COUNT(DISTINCT council) >= 2
ORDER BY combined_spend_gbp DESC, supplier_name
LIMIT 10

-- @step repro usl_or_inside_brackets
-- The same contract-cliff rule written with OR inside brackets. On my Zetaris (26 Oct 2026)
-- this returned Woking 115 / GBP 19,717,533.31 instead of 59 / GBP 8,086,068.60 - exactly the
-- answer of "A AND B AND C OR D", as if the brackets were dropped. The USL rows themselves are
-- identical to the source (221 rows, 86 in the window, 27 with an extension past vesting day).
SELECT c.council, COUNT(*) AS hard_cliff_contracts,
       ROUND(SUM(COALESCE(NULLIF(c.total_value_gbp, 0), c.annual_value_gbp, 0)), 2) AS stated_value_gbp
FROM lightning.metastore.vesting_day.west_surrey.contracts c
WHERE c.end_date >= '2026-10-03' AND c.end_date <= '2027-09-28'
  AND (c.max_extension_end IS NULL OR c.max_extension_end <= '2027-04-01')
GROUP BY c.council
ORDER BY c.council

-- @step repro source_or_inside_brackets
-- The same OR form on one registered source directly, without the USL: does it happen there too?
SELECT COUNT(*) AS hard_cliff_contracts,
       ROUND(SUM(COALESCE(NULLIF(total_value_gbp, 0), annual_value_gbp, 0)), 2) AS stated_value_gbp
FROM woking_pg.contracts
WHERE end_date >= '2026-10-03' AND end_date <= '2027-09-28'
  AND (max_extension_end IS NULL OR max_extension_end <= '2027-04-01')

-- @step dq register_contract_has_end_date
REGISTER DQ contract_has_end_date TABLE lightning.metastore.vesting_day.west_surrey.contracts AS
end_date IS NOT NULL

-- @step dq register_payment_is_positive
-- Woking publishes credit notes and zero lines in its spend file; the other two councils do not.
REGISTER DQ payment_is_positive TABLE lightning.metastore.vesting_day.west_surrey.spend AS
amount_gbp > 0

-- @step dq list_rules
LIST DQ USL lightning.metastore.vesting_day.west_surrey

-- @step dq run_contract_has_end_date
RUN DQ contract_has_end_date TABLE lightning.metastore.vesting_day.west_surrey.contracts

-- @step dq run_payment_is_positive
RUN DQ payment_is_positive TABLE lightning.metastore.vesting_day.west_surrey.spend

-- @step dq invalid_contracts_without_end_date
SHOW DQ INVALID RECORD contract_has_end_date TABLE lightning.metastore.vesting_day.west_surrey.contracts
