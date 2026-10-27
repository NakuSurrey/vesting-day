# Building with Zetaris - the VESTING DAY Unified Semantic Layer

This is the write-up of the Unified Semantic Layer we built over the three councils, step by
step, with where the evidence for each step is. Every result quoted here comes from the live run recorded in
`docs/ZETARIS_USL_EVIDENCE.md` (started 2026-10-26 22:54 UTC, 29 of 29 steps succeeded), which
`scripts/zetaris/build_usl.py` generated from Zetaris's own answers; the SQL of every step is in
`scripts/zetaris/usl.sql`. Sections 2a-2c are our own views and are labelled as such.

| Step | What the step asks for | What we did | Evidence |
|---|---|---|---|
| 1a Use case and sources | 3 or more data sources | Three councils, three separate databases, registered as three Zetaris sources | Section 1a; `scripts/zetaris/register_sources.sql` |
| 1b Onboard and explore | 2-3 queries per source | 3 queries per source, 9 in all | Evidence steps 1-9 |
| 1c Build and verify a USL | 1 USL and its DDL; 2-3 queries showing it active; 1 data-quality rule executed | USL `west_surrey`, 4 tables with keys; 4 queries, each giving the agent's own answer; 2 custom rules and 7 key rules, run | Evidence steps 10-29; section 1c |
| 2a Time saved vs hand coding | A write-up (bonus: compare a hand-coded part) | Section 2a, with a side-by-side comparison from our own code | This document |
| 2b How a USL helps our work | A write-up (bonus: a project and a forecast) | Section 2b | This document |
| 2c How to make the USL stronger | A PM-style requirement (bonus: a mocked feature) | Section 2c: five requirements, the first backed by a reproduced issue, and a mocked feature | This document; evidence steps 22-23 |

## 1a. Use case and data sources

The user is the finance lead of the West Surrey shadow authority. On 1 April 2027 Woking,
Guildford and Waverley become part of one new West Surrey council, but their data does not
merge: each publishes its spend,
its contracts register and its Council Tax Support scheme on its own cadence and in its own
shape. The questions that cannot wait for a migration are which suppliers the councils share,
which contracts end around vesting day, and which residents would get a different answer on day
one.

| Zetaris source | What it stands for | Tables | Rows (spend / contracts / policy clauses) |
|---|---|---|---|
| `woking_pg` | Woking Borough Council's published files | spend, contracts, policy_clause | 9,718 / 221 / 9 |
| `guildford_pg` | Guildford Borough Council's published files | spend, contracts, policy_clause | 6,883 / 179 / 9 |
| `waverley_pg` | Waverley Borough Council's published files | spend, contracts, policy_clause | 3,246 / 101 / 0 |

Each source is its own Postgres database, loaded from that council's published files and never
merged, read through a read-only login, on Zetaris's private Docker network with no port open
to the internet (`scripts/zetaris/build_load_sql.py`). Each is registered with
`CREATE DATASOURCE` and `REGISTER DATASOURCE TABLES` (`scripts/zetaris/register_sources.sql`).

## 1b. Exploratory queries - three per source

For each source: a spend profile (rows, total, date coverage), a contracts profile (end dates
and extension dates recorded) and its five biggest payees. What Zetaris returned:

| Source | Payments | Total GBP | Payment dates | Accounting periods | Contracts | No end date | Extension date recorded | End dates | Biggest payee |
|---|---|---|---|---|---|---|---|---|---|
| `woking_pg` | 9,718 | 64,974,729.21 | 2025-11-03 to 2026-04-30 | not published | 221 | 1 | 220 | 2025-11-30 to 2038-11-13 | Public Works Loan Board, GBP 32,772,792.34 |
| `guildford_pg` | 6,883 | 48,624,787.75 | 2026-04-02 to 2026-09-29 | 2026-01 to 2026-06 | 179 | 3 | 8 | 2019-11-22 to 2999-01-01 | McLaren Construction (South) Limited, GBP 4,885,840.72 |
| `waverley_pg` | 3,246 | 28,275,155.15 | not published | 2026-01 to 2026-06 | 101 | 0 | 0 | 2026-01-01 to 2029-05-29 | Biffa Municipal Limited, GBP 3,532,542.79 |

What the exploration showed, and what it changed:

- Three publishing practices. Woking gives payment dates but no accounting period; Waverley gives
  accounting periods but no payment date; Guildford gives both. So every answer carries a
  per-council window badge instead of pretending to one shared period.
- The extension field is filled on 220 of Woking's 221 contracts, 8 of Guildford's 179 and none
  of Waverley's 101. That is why the agent says "no extension date recorded", never "no extension
  option".
- Guildford's register holds a placeholder end date of 2999-01-01; the contract-cliff window
  (180 days either side of vesting day) excludes it.

## 1c. The USL, its DDL, the queries that show it is active, and data quality

The model is `lightning.metastore.vesting_day.west_surrey` (USL id 952 on our Zetaris): four
tables, one primary key each and a foreign key from every table to `council`.

```sql
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
```

Each table is activated with one `SELECT ... UNION ALL ...` over the three sources, so the USL
binds the councils without copying them. `council` is built from the data itself (each source's
council name and the Zetaris source it lives in).

**Queries on the activated USL.** The runner also ran each one on the SAMPLE_MODE copy of the
councils' files that the agent uses, and recorded whether the answers are the same.

| Query (evidence step) | Zetaris answer through the USL | Same as the agent's data |
|---|---|---|
| Payments per council, joined to `council` (18) | Guildford 6,883 / GBP 48,624,787.75; Waverley 3,246 / GBP 28,275,155.15; Woking 9,718 / GBP 64,974,729.21 | yes |
| Contract cliff: ending within 180 days of vesting day, no extension date recorded past it (19) | Guildford 48 / GBP 12,074,354.70; Waverley 66 / GBP 2,511,101.47; Woking 59 / GBP 8,086,068.60 - together 173 / GBP 22,671,524.77, the agent's 173 / GBP 22,671,525 | yes |
| Supplier names paid by two or more councils, exact names (20) | 113 | yes |
| The ten largest of those by combined spend (21) | Surrey County Council (3 councils, GBP 4,448,671.37), Waverley Borough Council, Pilon Limited, ... | yes |

The exact-name count (113 names) is deliberately simple; the agent's Resolver goes further,
normalising names and comparing them in pairs (228 pairs), and only a person confirms a near
match.

**Data quality.** Two custom rules, plus the seven key rules Zetaris generated from the DDL
(four primary keys, three foreign keys); `LIST DQ USL` shows all nine.

| Rule (evidence step) | Table | Expression | Total | Valid | Invalid |
|---|---|---|---|---|---|
| `contract_has_end_date` (27) | contracts | `end_date IS NOT NULL` | 501 | 497 | 4 |
| `payment_is_positive` (28) | spend | `amount_gbp > 0` | 19,847 | 19,595 | 252 |

- The four contracts without an end date (step 29, each with its provenance id) are Woking
  CCR/2627/0063 and Guildford CR001810, CR001820 and CR001909 - exactly the four the agent lists
  separately as "no usable end date". Zetaris's rule and the agent agree.
- The 252 lines that are zero or negative are all Woking's: Woking publishes credit notes and
  zero lines in its spend file; Guildford and Waverley do not. A merged finance team has to treat
  those as credits, not payments - another practice that differs between the councils.

**How the agent uses it.** Setting `ZETARIS_USL=lightning.metastore.vesting_day.west_surrey`
makes the agent's Researcher read through the USL instead of its own UNION over the three
sources; `tests/test_zetaris_usl.py` checks that every Researcher query then returns the same
rows as SAMPLE_MODE. The committed live runs `live-01` to `live-06` were made before the USL
existed and read the three sources directly.

**What we found while building it.** On our Zetaris, a filter of the form
`A AND B AND (C OR D)` on a USL table returned the answer of `A AND B AND C OR D`, as if the
brackets were dropped:

- Our first contract-cliff query used `AND (max_extension_end IS NULL OR max_extension_end <= '2027-04-01')`
  and returned Woking 115 contracts / GBP 19,717,533.31 instead of 59 / GBP 8,086,068.60.
- A diagnostic query showed the USL rows are identical to the source (221 Woking contracts, 86 in
  the window, 27 with an extension past vesting day), and the bracket-free reading gives 115 /
  GBP 19,717,533.31 to the penny.
- The same query on the registered source `woking_pg.contracts` directly gives the correct 59
  (evidence step 23), so we saw it only through the USL (step 22 reproduces it).
- We rewrote the USL query with `CASE` (no `OR`), and kept both forms as repro steps. The agent's
  own SQL has one `AND (x OR y)`, in its "no usable end date" lookup; there the second test
  (`end_date = ''`) can never be true for a date, so the answer is the same either way - and the
  live run's 4 rows match.

## 2a. Did the USL save us time, compared with hand coding? (our view)

Honestly, not in this project. We hand-coded the federation first and built the USL on the last
day, so the USL came on top of work already done. It took about 40 minutes from the first
USL commit to a 29-of-29 run, across five live runs (one repeated by mistake) that hit three
problems in turn: a missing parent namespace, a NOT NULL column fed by a nullable expression,
and the bracket issue above. The whole 29-step build then runs in
about 15 seconds of Zetaris time.

What we hand-coded, and what a USL built on day one would have replaced:

- **The UNION in every query.** Our adapter renders every table as
  `(SELECT * FROM woking_pg.contracts UNION ALL SELECT * FROM guildford_pg.contracts UNION ALL SELECT * FROM waverley_pg.contracts) AS contracts`;
  through the USL it is `lightning.metastore.vesting_day.west_surrey.contracts`. Our adapter
  already kept that in one place, so the saving there is small.
- **Hand-written checks.** The agent finds contracts with no usable end date with its own query
  and a classification step in Python; in the USL it is one `REGISTER DQ` statement and
  `RUN DQ`, with the same four rows and their provenance. The seven key checks (unique ids,
  every row's council exists) we never wrote at all - the USL generated them from the DDL.
- **A schema other people can see.** `LOAD USL` returns the model as JSON; ours lived in code.

What it would not have replaced: Zetaris's REST API returns every value as text, typed USL
columns included, so the adapter's conversion of numbers and dates stays; and the bracket issue
needs care with `OR` in USL filters.

**Bonus - one part compared side by side, from our own code.** The same question asked both ways:

```sql
-- Hand coded: what the agent's Researcher sends today (contracts in the window; the
-- extension rule is applied afterwards in Python; column list shortened here)
SELECT provenance_id, council, end_date, max_extension_end, annual_value_gbp, total_value_gbp
FROM (SELECT * FROM woking_pg.contracts UNION ALL SELECT * FROM guildford_pg.contracts
      UNION ALL SELECT * FROM waverley_pg.contracts) AS contracts
WHERE end_date IS NOT NULL AND end_date >= '2026-10-03' AND end_date <= '2027-09-28'

-- Through the USL: one table, the whole rule in SQL, joined to the council dimension
SELECT c.council, k.zetaris_source, COUNT(*) AS hard_cliff_contracts, ...
FROM lightning.metastore.vesting_day.west_surrey.contracts c
JOIN lightning.metastore.vesting_day.west_surrey.council k ON c.council = k.council
WHERE c.end_date >= '2026-10-03' AND c.end_date <= '2027-09-28'
  AND CASE WHEN c.max_extension_end IS NULL THEN 1 WHEN c.max_extension_end <= '2027-04-01' THEN 1 ELSE 0 END = 1
GROUP BY c.council, k.zetaris_source
```

The hand-coded query returns the 202 contracts in the window and the agent's Python step keeps
173; the USL query returns the 173 directly - both GBP 22,671,524.77. And for the data-quality
check: the agent's
hand-coded `contracts_without_end_date` query returns 4 rows; `RUN DQ contract_has_end_date`
returns 501 total, 497 valid, 4 invalid - the same four contracts.

## 2b. How a USL would help, and not help, in this kind of work (our view)

It would help a merging council's finance team because:

- One named model of all the councils' data, with keys, that any analyst can query by table
  name, instead of each person rebuilding the UNION and the joins.
- Data-quality rules that run where the data is, so the merger's data-cleansing work becomes a
  list Zetaris produces: 252 credit and zero lines, 4 contracts without an end date, and checks
  on every key, rerun in seconds after each council publishes again.
- The councils stay the owners of their data; the USL only describes and binds it, which is the
  only arrangement that works before vesting day.

It would not help, or not yet:

- With text-only REST answers, every client still has to convert types.
- With the bracket issue, a finance team cannot yet write any `OR` filter on a USL table without
  checking it against the sources.
- It does not decide anything: matching supplier names, deciding which pairs are the same
  company, and approving actions stay with the agents and a person.

**Bonus - a project that would benefit, and a forecast.** The rest of Surrey's reorganisation:
every remaining council in each new authority publishes the same three kinds of file in its own
shape. Today we turn each council's files into one common shape offline, in a 440-line Python
script (`scripts/build_sample_data.py`), before loading them. With a USL, each council's files
could be registered as they are and mapped to the common model in that council's branch of each
activation (about 15 lines of SQL per table per council, judging by our own activations), and
every key and data-quality rule would then apply to the new council with no new code.
Our forecast - an estimate, not a measurement: adding a council would shrink from extending and
re-testing an offline mapping script, a load and the agent's checks, to registering a source,
adding one branch to each activation and rerunning a build that takes seconds.

## 2c. How to make the USL stronger - requirements, written as a PM (our view)

**R1. Filters on USL tables must keep their brackets (correctness, highest priority).**
- Problem: on our instance, `WHERE A AND B AND (C OR D)` on a USL table returned the rows of
  `A AND B AND C OR D`. The same filter on the registered source was correct.
- Impact: a silent wrong answer. Our contract-cliff count rose from 59 to 115 contracts and the
  value at risk was overstated by GBP 11,631,464.71, with no error. A finance lead would act on it.
- Repro: evidence steps 22 and 23 (`scripts/zetaris/usl.sql`, `repro` steps), against the USL
  and the source, on the same data.
- Acceptance: any filter on a USL table gives the same rows as the same filter on the activation
  query's result; a test suite of boolean shapes (`AND (OR)`, `OR (AND)`, `NOT (OR)`) over a USL
  built on two or more sources passes.

**R2. Typed REST answers.** Return numbers and dates as JSON numbers and ISO dates, or give each
header a type. Today every value is text, so every client writes its own conversion.

**R3. The SQL Workspace should run a COMPILE USL with several tables.** It splits editor text at
`;`, which breaks `COMPILE USL ... DDL` with more than one `CREATE TABLE`. Recognise the DDL
block, or say in the error that the New USL screen or an API call is needed.

**R4. A clean instance should accept a first namespace.** On an instance with no USL,
`CREATE NAMESPACE lightning.metastore.<name>` fails with a NamespaceException about the parent
namespace (Zetaris's getting-started guide quotes it as "parent namespace : metastore is not
existing"). Create `lightning.metastore` on first use, or name the fix in the message.

**R5. Activation errors should point at the fix.** "Column 'amount_gbp': nullable -> NOT NULL"
was right, but our expression was already a COALESCE wrapped in a CAST. Say that a CAST makes an
expression nullable and suggest putting COALESCE outermost.

**Bonus - a mocked feature: activate one table from a set of like-shaped sources.** Fragmented
data usually means many sources of the same shape. Today each of our tables needs a
`UNION ALL` branch per source; the contracts activation alone is 51 lines of SQL for three
councils. Proposed syntax (this does not exist in Zetaris today; it is a mock of the feature):

```sql
ACTIVATE USL TABLE lightning.metastore.vesting_day.west_surrey.contracts
  FROM SOURCES (woking_pg, guildford_pg, waverley_pg) TABLE contracts
  MAP SOURCE guildford_pg (end_date AS CAST(end_dt AS DATE))   -- only where a source differs
  ADD COLUMN zetaris_source AS SOURCE_NAME()
```

The resulting USL would be the same four tables, but adding a fourth council would be one more
name in `FROM SOURCES (...)`, and the `council` table could be derived from `SOURCE_NAME()`
instead of being built by hand.
