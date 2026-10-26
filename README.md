# VESTING DAY

An agent for England's merging councils. On 1 April 2027 Woking, Guildford and Waverley
(with the rest of West Surrey) become one new unitary authority. Their data does not: each
council publishes its spend on its own cadence and schema, keeps its own contracts register,
and runs its own Council Tax Support scheme. VESTING DAY queries that fragmented data in
place, resolves which suppliers the councils share, remembers every human decision so later
answers change, finds the contracts that fall off a cliff around vesting day and the policy
gaps residents hit on day one, and drafts the first actions - under a human approval gate.

Open Agent Hackathon 2026, Track 1 (Solving Fragmented Intelligence). Solo entry.

## What it does (real data, real numbers)

| Ask it | It answers with |
|---|---|
| Which suppliers do Woking, Guildford and Waverley share? | 228 supplier pairs shared with confidence across the councils' newest published windows (GBP 34.8m combined), 217 pairs that need a human, every row with a provenance id |
| Confirm that 'A' (Waverley) is the same supplier as 'B' (Guildford) | A human decision stored in Meterless H-MEM. The next overlap answer resolves that pair "using decision mem-N" |
| Which contracts end within six months of vesting day? | 173 contracts worth GBP 22.7m with no extension option past 1 April 2027; the largest (GBP 8.5m, Guildford) ends 13 days after vesting day. One novation letter drafted and held for approval |
| Where do the Council Tax Support schemes differ? | 4 of 9 clauses differ (capital limit GBP 10,000 vs 6,000; minimum award GBP 5 vs 10; backdating 6 months vs 1 month; Guildford excludes bands F-H), each citing a page of the published scheme |

Everything above comes from the councils' own published files, downloaded 25 Oct 2026
(`data/raw/MANIFEST.md` has every URL and hash). Nothing is hardcoded: the numbers are
computed at run time from `data/sample`, and differ when the data or the decisions change.

## Run it in two minutes (no credentials, no services, no network)

```bash
git clone https://github.com/NakuSurrey/vesting-day
cd vesting-day
uv sync                      # Python 3.12; https://docs.astral.sh/uv/
python run.py                # serves POST /run on 0.0.0.0:8000
```

With no `.env` the app runs in SAMPLE_MODE: the same agents and the same logic over the
cached published data, with a deterministic template in place of the model (badged
`sample-mode/template`). Then, in another terminal:

```bash
curl -s -X POST localhost:8000/run -H 'Content-Type: application/json' \
  -d @input_examples/01_supplier_overlap.json | python -m json.tool | head -40
```

Or without the server:

```bash
python run.py --input input_examples/01_supplier_overlap.json
python run.py --query "Which contracts end within six months of vesting day?"
```

Run the examples in order to watch memory change the answer:

```bash
python run.py --reset-memory --input input_examples/01_supplier_overlap.json   # Unit4 pair: pending
python run.py --input input_examples/02_confirm_match.json                      # human confirms -> mem-1
python run.py --input input_examples/03_supplier_overlap_after_decision.json    # pair: confirmed, "resolved using decision mem-1"
```

Each run writes `logs/trace-<run_id>.jsonl` - one line per agent action - and echoes it to
the console. The response shape is the HackOS contract (`run_id`, `status`, `output`,
`agents`, `trace_id`, `log_file`, `execution_time_seconds`); errors come back structured,
never as a crash.

Docker: `docker build -t vesting-day . && docker run --rm -p 8000:8000 vesting-day`
(the CI builds it and runs it with `--network none`).

## Tests

```bash
uv sync --all-groups
uv run pytest -q          # 25 tests
```

- `tests/test_hmem_conformance.py` - the official H-MEM conformance suite, ported to pytest,
  run against the unmodified upstream vectors: 13/13.
- `tests/test_hmem_golden.py` - our Python engine reproduces the TypeScript reference
  bit-for-bit (embeddings, ranking, scores, conflict resolution).
- `tests/test_run_sample_mode.py` - the run interface, real handoffs and a Critic bounce in
  the trace, provenance on every number, the memory loop changing a later answer, the
  approval gate, the structured error for unsupported requests.

## How it works

```
POST /run  ->  Router  ->  Researcher  ->  Resolver  <->  Memory (H-MEM)
                                  |             |
                                  v             v
                               Critic  <-----  (bounce: below-bar matches go back)
                                  |
                                  v
                               Writer (Nemotron via Nightshift | template)  ->  Critic  ->  ApprovalGate
```

Seven agents, each a distinct code path in `app/agents/`:

- **Router** classifies free text into a flow (supplier overlap, confirm a match, contract
  cliff, policy gap, approve a draft) or returns a structured `UnsupportedRequest`.
- **Researcher** runs SQL against the data layer. Live: Zetaris REST, query-in-place over the
  three councils' registered sources. Sample: the same SQL over SQLite loaded from the
  cached files. The agent code is identical; only the adapter differs.
- **Resolver** normalises supplier names, scores every cross-council pair (exact 0.95;
  fuzzy >= 0.92; 0.70-0.92 is the judge band), applies decisions Memory recalled, asks
  Companies House when a key is present, and in live mode asks Nemotron about the band.
- **Memory** is the Meterless H-MEM engine (`app/engines/hmem`): human decisions are stored
  as long-term memories with provenance and recalled through the engine's ranked retrieval;
  every read and write lands in its append-only ledger (`data/memory/ledger.jsonl`).
- **Critic** checks thresholds and provenance and sends work back: pairs below the
  confirmation bar return to the Resolver (retry 1), drafts with a number that is not in
  the evidence return to the Writer.
- **Writer** drafts briefings and letters from the evidence table only. Live: NVIDIA
  Nemotron (`nvidia/nemotron-3.5-lightning-30b-a3b`) through Meterless Nightshift, with
  the signed compute receipt id kept. Sample: a deterministic template.
- **ApprovalGate** holds every draft as `pending` and records human confirmations. Nothing
  is ever sent.

Every displayed number carries a provenance id (`council:file:row`) back to the published
file; every generated text carries its model badge; synthetic data (the eight test residents
in `data/sample/residents_synthetic.csv`) is labelled SYNTHETIC wherever it appears.

## Live mode (Zetaris + Nightshift)

Copy `.env.example` to `.env` and fill in:

- `ZETARIS_REST_URL`, `ZETARIS_ORG_ID`, `ZETARIS_API_KEY` - a Zetaris instance with the three
  councils registered as three separate sources. Each council is its own Postgres database,
  standing in for that council's own system: loaded from its published files and never
  merged (`scripts/zetaris/` has the load script and the Lightning SQL). We run Zetaris on a
  16 GB Hetzner server and reach it over an SSH tunnel so the URL stays `localhost:8888`.
- `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN` - from Nightshift's Console on the machine
  running it. The NVIDIA API key is set inside Nightshift's Providers, never in this app.
- `METERLESS_MODEL` - we pin `nvidia/nemotron-3.5-lightning-30b-a3b` so the NVIDIA model is
  named on every request (Nightshift's `meterless/auto` could route elsewhere).

Set `SAMPLE_MODE=false`. If either service is unreachable the run returns a structured
error (`UpstreamTimeout`, recoverable) and says so, rather than silently switching data.

## Data

`data/raw/` holds the files exactly as published; `scripts/build_sample_data.py` maps the
three schemas to one (`data/sample/spend.csv`, `contracts.csv`) and
`scripts/build_policy_clauses.py` builds the clause table with page citations, verifying each
quote against the PDF.

Why the windows differ: Woking publishes monthly and its newest file is April 2026;
Guildford publishes financial-year quarters and is at Jul-Sep 2026; Waverley publishes
half-yearly by accounting period and is at Apr-Sep 2026. There is no single month all three
have published beyond April 2026, so we take each council's newest six months and badge
every answer with its window. That mismatch is the fragmentation the project exists to
federate.

Data handling: rows whose payee looks like a natural person are dropped by the build script
(395 rows), and council card-holder names are never copied. Published under each council's
open data terms.

## Limitations, stated plainly

- Only the Lightning Nemotron lane is used. The Super-class endpoints were retired, excluded
  or end-of-life for this account during the event, so Lightning does both matching and drafting.
- Supplier identity below the exact / Companies-House bar is never asserted; those pairs are
  queued for a human. The fuzzy heuristics are deliberately conservative.
- The policy flow covers Woking and Guildford; Waverley's scheme is not yet in the clause table.
- Drafts are held, never sent. Approval records intent only.

## Sponsor technology

See `docs/SPONSOR_TECHNOLOGY.md` for exactly how Zetaris, the Meterless H-MEM engine, Meterless
Nightshift and NVIDIA Nemotron are used, and the test for each.

## Third party

`third_party/hmem/vectors.json` is the Meterless H-MEM conformance suite, copied unmodified
(Apache-2.0, see `third_party/hmem/NOTICE`). `app/engines/hmem` is our own port of the
Meterless TypeScript reference. Everything else in this repository was written during the
hackathon (22-27 Oct 2026). Licence: Apache-2.0.
