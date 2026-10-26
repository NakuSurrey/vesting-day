# Sponsor Technology Explanation - VESTING DAY

How each sponsor technology is used, where it lives in the code, and the test that shows it working.

## Zetaris - the data layer

**What it does here.** Three councils publish their spend, contracts and Council Tax Support
schemes on different cadences, in different shapes, with different lags. Zetaris lets the
agent query all three as one, in place, without a migration: the three sources are
registered as `woking_pg`, `guildford_pg` and `waverley_pg` and the Researcher agent's SQL
runs across all of them in one statement.

**Where.** `app/adapters/datalayer.py` (`ZetarisDataLayer`) speaks the REST contract from the
Participant Setup Guide: `POST /sql-editor/sqls/run`, Bearer key, `X-Org-ID`, a fresh
`X-Request-ID` per call, body `{queryId, sql, source: "SqlEditor", limit}`, rows in `.data`,
three retries then a structured `UpstreamTimeout`. `scripts/zetaris/register_sources.sql`
registers the sources; `scripts/zetaris/schema.sql` and `build_load_sql.py` build them -
one Postgres database per council next to Zetaris, loaded from the published files, never
merged, and reachable only on its Docker network.
`docs/ZETARIS_SETUP.md` is the runbook.

**Test / evidence.** Live traces in `logs/` carry `query_data_layer` events whose
`data_layer` names Zetaris. In SAMPLE_MODE the same Researcher code runs the same SQL over a
local SQLite cache of the published files (`LocalDataLayer`), which `tests/test_run_sample_mode.py`
exercises end to end - so the agent path is identical in both modes and only the adapter changes.

## Meterless Engine: H-MEM - the memory

**What it does here.** H-MEM is the project's decision memory. When a person confirms that
two supplier records are the same organisation, the Memory agent stores it as a long-term,
human-sourced memory with provenance. The next overlap question recalls it through the
engine's ranked retrieval and the Resolver resolves that pair "using decision mem-N". The
engine visibly changes a later answer, and every read and write lands in its append-only
trust ledger.

**Where.** `app/engines/hmem/` is our Python port of the Meterless reference (ten modules:
types, embeddings, store, ledger, retrieval, mining, conflicts, sleep, dreaming, facade).
`app/agents/memory.py` is the agent that uses it; `app/flows/confirm_match.py` writes
decisions; `app/flows/supplier_overlap.py` recalls them. State persists in
`data/memory/state.json` and `data/memory/ledger.jsonl`.

**Test / evidence.**
- `tests/test_hmem_conformance.py` - the official conformance runner ported to pytest,
  against the unmodified upstream vectors (`third_party/hmem/vectors.json`): **13/13**
  (record validation, feedback deltas, ranking order, sleep guardrails, conflict gate,
  ledger audit, dream boundary).
- `tests/test_hmem_golden.py` - bit-exact parity with the TypeScript reference on fixed
  scenarios (embeddings, cosine, ranking, scores, reinjection text, conflict resolution).
- `tests/test_run_sample_mode.py::test_memory_changes_a_later_answer` - the product feature:
  overlap, confirm, overlap again; the pair becomes `confirmed` with `decision_id`, the
  summary says "resolved from remembered human decisions (mem-1)", and the engine ledger
  shows `create` then `read`.
Run: `uv run pytest -q`.

## Meterless Nightshift - the primary AI provider

**What it does here.** All model calls go through Nightshift's OpenAI-compatible endpoint
on the builder's machine (`METERLESS_BASE_URL`, Bearer `METERLESS_RUNTIME_TOKEN`, headers
`meterless-app` and `meterless-scope: user`). The NVIDIA API key is configured inside
Nightshift's Providers, never in this app. Each response's signed Meterless compute receipt
(`receipt_id`, `winning_route.model`, provider) is kept and written to the trace.

**Where.** `app/adapters/nightshift.py` (`NightshiftClient`). Two rules it enforces for
Nemotron thinking models: `reasoning_effort: "none"` and `max_tokens >= 256`, otherwise the
model spends its budget on hidden reasoning and returns no text.

**Test / evidence.** Live traces: every `draft` and `judge_matches` event carries `model`
and `receipt_id`. In SAMPLE_MODE the Writer uses `TemplateModel`, badged
`sample-mode/template`, so no output is ever mistaken for a model's.

## NVIDIA Nemotron

**What it does here.** `nvidia/nemotron-3.5-lightning-30b-a3b`, through Nightshift, powers
two working features: the Writer (briefings, a novation letter, an options note, all bound
to the evidence table and checked by the Critic) and the Resolver's match judge for supplier
pairs in the uncertain band. The model is pinned by name rather than `meterless/auto`, so
the Nemotron model is named on every request in the trace.

**Where.** `app/agents/writer.py`, `app/agents/resolver.py` (`judge_band`), `METERLESS_MODEL`
in `.env.example`.

**Limitation, stated plainly.** Only the Lightning lane is used. During the event the
Super-class endpoints were retired, excluded or end-of-life for this account, so Lightning
does both the matching judgement and the drafting.

## What is claimed and what is not

- Claimed: Zetaris as the data layer; the H-MEM engine, ported and conformance-tested, in a
  working feature; Nightshift as the primary provider; Nemotron Lightning through it.
- Not claimed: the other Meterless engines (World Model, Markovian, Scout Intent) are not
  used. The Router is a deterministic classifier, not Scout Intent.
- Third party: `third_party/hmem/vectors.json` (Apache-2.0, Meterless) is the only copied
  artefact; `app/engines/hmem` is our own port of the reference.
