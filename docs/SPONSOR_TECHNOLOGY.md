# Sponsor Technology Explanation - VESTING DAY

Track: Solving Fragmented Intelligence. How each sponsor technology is used, where it lives in
the code, and the test or trace that shows it working. If you removed any of them, the agent
would stop doing its job: without Zetaris it has no data, without H-MEM a human decision is
forgotten by the next answer, without Nightshift and Nemotron there is no live drafting or
match suggestion.

## Zetaris - the data layer

**What it does here.** Three councils publish their spend, contracts and Council Tax Support
schemes on different cadences, in different shapes, with different lags. Zetaris lets the
agent query all three as one, in place, without a migration: each council is its own
Postgres database (standing in for that council's own system, loaded from its published
files and never merged), registered in Zetaris as `woking_pg`, `guildford_pg` and
`waverley_pg`. The Researcher agent's SQL runs across all three in one federated statement.
A federated count through Zetaris matched the published files to the penny (Woking 9,718
payments / GBP 64,974,729.21; Guildford 6,883 / GBP 48,624,787.75; Waverley 3,246 /
GBP 28,275,155.15).

**How it is integrated.** `app/adapters/datalayer.py` (`ZetarisDataLayer`) speaks the REST
contract from the Participant Setup Guide: `POST /sql-editor/sqls/run`, Bearer key,
`X-Org-ID`, a fresh `X-Request-ID` per call, body `{queryId, sql, source: "SqlEditor", limit}`.
It reads the live answer shape (`{"headers": [...], "data": [[...]], "total": n}`, every value
as text), coerces exactly the number and date columns the agents use so live rows match
SAMPLE_MODE rows, refuses a truncated answer, and retries three times before returning a
structured `UpstreamTimeout`. `scripts/zetaris/build_load_sql.py` builds the three databases
with a read-only `vd_reader` login; `scripts/zetaris/register_sources.sql` registers them
(`CREATE DATASOURCE` + `REGISTER DATASOURCE TABLES`). The databases sit on Zetaris's private
Docker network with no port open to the internet. `docs/ZETARIS_SETUP.md` is the runbook.

**Unified Semantic Layer.** Over the three sources we built the USL
`lightning.metastore.vesting_day.west_surrey`: four tables (`council`, `spend`, `contracts`,
`policy_clause`) with primary keys and a foreign key from each to `council`, each activated with
one SELECT over the three sources, so nothing is copied. Through it Zetaris gives the agent's own
answers (payments per council; the contract cliff, 173 contracts / GBP 22,671,524.77), and two
data-quality rules run where the data is: `contract_has_end_date` (501 contracts, 4 invalid -
the same four the agent lists) and `payment_is_positive` (19,847 lines, 252 invalid - Woking's
credit and zero lines). Setting `ZETARIS_USL` makes the agent's Researcher read through the USL.
Building it we found that a filter `A AND B AND (C OR D)` on a USL table was answered as if the
brackets were dropped (59 contracts became 115); the same filter on the source was correct. The
USL query avoids `OR`, and the issue is kept as a reproducible step. `docs/ZETARIS_USL.md` maps
each of Zetaris's evaluation criteria to the evidence.

**Test / evidence.**
- Live traces `logs/trace-live-0N.jsonl`: every `query_data_layer` event names
  `zetaris (federated query-in-place over woking_pg, guildford_pg, waverley_pg)`.
- `tests/test_datalayer_zetaris.py`: a fake Zetaris in the real answer shape, backed by three
  separate sources; every Researcher query returns exactly the rows SAMPLE_MODE returns, and
  a partial answer is refused. Proven to fail on the adapter before the fix.
- `docs/ZETARIS_USL_EVIDENCE.md` and `logs/zetaris-usl-build.jsonl`: the live USL build, 29 of
  29 steps, written by `scripts/zetaris/build_usl.py` from Zetaris's answers - 9 exploratory
  queries on the sources, the DDL, the activations, 4 USL queries that each match the agent's
  data, the bracket repro, and both data-quality rules run.
- `tests/test_zetaris_usl.py`: the USL mirrors the council tables, its queries give the agent's
  own contract-cliff answer, and every Researcher query read through it matches SAMPLE_MODE.

## Meterless - the H-MEM engine (memory) and Nightshift (primary AI provider)

### H-MEM engine - decision memory

**What it does here.** When a person confirms that two supplier records are the same
organisation, the Memory agent stores it as a long-term, human-sourced memory with
provenance. The next overlap question recalls it through the engine's ranked retrieval, the
Resolver resolves that pair "using decision mem-N", and the Critic will not let the briefing
leave without naming that decision. The engine visibly changes a later answer, and every read
and write lands in its append-only trust ledger.

**How it is integrated.** `app/engines/hmem/` is our Python port of the Meterless reference
(types, embeddings, store, ledger, retrieval, mining, conflicts, sleep, dreaming, facade).
`app/agents/memory.py` is the agent that uses it; `app/flows/confirm_match.py` writes
decisions; `app/flows/supplier_overlap.py` recalls them. State persists in
`data/memory/state.json` and `data/memory/ledger.jsonl`.

**Test / evidence.**
- `tests/test_hmem_conformance.py` - the official conformance runner ported to pytest, against
  the unmodified upstream vectors (`third_party/hmem/vectors.json`): **13/13**.
- `tests/test_hmem_golden.py` - bit-exact parity with the TypeScript reference (embeddings,
  cosine, ranking, scores, reinjection text, conflict resolution).
- `tests/test_run_sample_mode.py::test_memory_changes_a_later_answer` - overlap, confirm,
  overlap again: the pair is resolved with `decision_id` `mem-1`, and the ledger shows
  `create` then `read`.
- `tests/test_live_judge_hints.py` - a live briefing that leaves out a recalled decision is
  bounced by the Critic; the retry or the template names it.
- Live: `logs/response-live-02.json` stores `mem-1`; `logs/response-live-03.json` is a live
  Nemotron briefing that says "One pair was resolved using a remembered human decision (mem-1)".

### Nightshift - the primary AI provider

**What it does here.** Every model call goes through Nightshift's OpenAI-compatible endpoint
on the builder's machine (`METERLESS_BASE_URL`, Bearer `METERLESS_RUNTIME_TOKEN`). The NVIDIA
API key is configured inside Nightshift's Providers, never in this app. Each response's signed
Meterless compute receipt (`receipt_id`, model, provider) is kept and written to the trace.

**How it is integrated.** `app/adapters/nightshift.py` (`NightshiftClient`). Two rules it
enforces for Nemotron: `reasoning_effort: "none"` and `max_tokens >= 256`, otherwise the
model spends its budget on hidden reasoning and returns no text.

**Test / evidence.** Live traces: every `draft` and `judge_matches` event carries the model and
a `receipt_id` (14 receipts in each live supplier-overlap run). In SAMPLE_MODE the Writer uses
`TemplateModel`, badged `sample-mode/template`, so no output is ever mistaken for a model's.

## NVIDIA - Nemotron

**Where it contributes.** `nvidia/nemotron-3.5-lightning-30b-a3b`, through Nightshift, powers
three working features:
- the Planner: for a broad question ("What are the biggest risks on vesting day?") Nemotron
  proposes the plan as JSON - which of the three checks to run, in what order, with what contract
  window - and the code validates it against the checks that exist. Unknown steps are dropped, an
  unusable plan is replaced by the rule-based one, and the trace records which happened, with the
  receipt;
- the Writer: the supplier briefing, the novation letter and the Council Tax Support options
  note, each written from the evidence table only and checked by the Critic before the
  ApprovalGate holds it;
- the Resolver's match judge for supplier pairs in the uncertain band: it suggests SAME or
  DIFFERENT, and that suggestion orders the human review queue. It never confirms a pair -
  only a person does.

The model is pinned by name (`METERLESS_MODEL`), so the Nemotron model is named on every
request in the trace. Code: `app/agents/planner.py`, `app/agents/writer.py`,
`app/agents/resolver.py` (`judge_band`).

**Limitation, stated plainly.** Only the Lightning lane is used. During the event the
Super-class endpoints were retired, excluded or end-of-life for this account, so Lightning does
both the matching suggestions and the drafting.

## Cursor - development

Cursor was not used. The event made Cursor optional on 22 Oct 2026 and allowed any AI coding
tool; this project was built with Claude Code. Every change was reviewed, tested and committed
by the author, and the commit history is the record of the build.

## What was unique

- **The model decides the plan; the code keeps it safe.** For a broad question Nemotron chooses
  the checks, and the Planner validates, delegates, assesses and revises - every decision is a
  trace line with the model and receipt. In SAMPLE_MODE a rule-based planner, badged as such, does
  the same job, so judges see the same control flow without credentials.
- **Memory that changes the answer, and has to say so.** A human decision stored in H-MEM
  changes the next answer, and the Critic rejects any briefing that relied on a remembered
  decision without naming it. The live briefing says "resolved using a remembered human
  decision (mem-1)" - the memory is visible to the reader, not only in the trace.
- **The model advises, a human decides, the Critic enforces.** Nemotron's match opinion is a
  suggestion that orders the human queue; it can never move a pair to "confirmed". When the
  live model wrote "confirmed as shared" anyway, the Critic rejected the draft with the exact
  reason, the retry fixed it, and the trace records both. A model that keeps over-claiming is
  replaced by the evidence-only template.
- **Federation, not migration, with the live path proven equal to the offline path.** Three
  council databases are never merged; Zetaris queries them in place behind a read-only login
  with no open port. A test replays Zetaris's real answer shape and proves every live query
  returns exactly what SAMPLE_MODE returns, so the judge-runnable path and the live path are
  the same agent.
- **Every number is accountable.** Each figure carries a `council:file:row` provenance id, each
  generated sentence carries its model badge and Meterless receipt, and SYNTHETIC test
  residents are labelled wherever they appear.

## What is claimed and what is not

- Claimed: Zetaris as the data layer; the H-MEM engine, ported and conformance-tested, in a
  working feature; Nightshift as the primary provider; Nemotron Lightning through it.
- Not claimed: the other Meterless engines (World Model, Markovian, Scout Intent) are not
  used. The Router is a deterministic classifier, not Scout Intent. Cursor was not used.
- Third party: `third_party/hmem/vectors.json` (Apache-2.0, Meterless) is the only copied
  artefact; `app/engines/hmem` is our own port of the reference.
