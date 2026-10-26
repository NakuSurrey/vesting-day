# Demo video script (target 3 minutes, limit 1-4)

Three moments the judges look for: an agent querying Zetaris, the Meterless engine doing
something that changes the answer, and one real request through Nightshift with the
Nemotron model visible. Everything on screen is a real run; nothing is staged.

## 0:00 - 0:25  The problem (slide, voice over)
"On 1 April 2027 Woking, Guildford and Waverley stop existing and West Surrey begins. Their
data does not merge on that day. Woking publishes spend monthly and is six months behind;
Guildford publishes financial-year quarters; Waverley publishes half-years by accounting
period with no payment date. Three registers, three Council Tax Support schemes. Someone
has to answer the merger's questions now, without a migration that does not exist yet."

## 0:25 - 0:40  What VESTING DAY is (architecture slide)
"Seven agents. The Researcher queries all three councils through Zetaris in one statement.
The Resolver works out which suppliers they share. Memory is the Meterless H-MEM engine.
The Critic rejects anything below the bar. The Writer drafts through Nightshift on NVIDIA
Nemotron. Nothing leaves without a human at the approval gate."

## 0:40 - 1:20  Moment 1: Zetaris (terminal + Zetaris UI)
Show the Zetaris SQL editor with the three datasources (woking_pg, guildford_pg,
waverley_pg). Run `python run.py --query "Which suppliers do Woking, Guildford and Waverley
share?"`. Point at the trace line: Researcher -> `query_data_layer` -> `zetaris (federated
query-in-place over woking_pg, guildford_pg, waverley_pg)` -> 2194 rows. Then the summary:
228 shared supplier pairs, GBP 34.8m, 220 need a human. Show one row's provenance id and
open the council's file at that row.

## 1:20 - 2:05  Moment 2: H-MEM changes the answer (terminal)
Point at the Unit4 pair in "needs a human" (similarity 0.979, no Companies House in sample).
Run the confirm request. Show: "Stored in H-MEM as mem-1 (long_term, confidence 1.0, source
human:approval-gate)". Open `data/memory/ledger.jsonl`: the `create` entry. Run the overlap
again. Show the summary line "1 of them resolved from remembered human decisions (mem-1)"
and the row: status confirmed, "resolved using decision mem-1". Mention: the engine is our
Python port, 13/13 on the official conformance vectors - `uv run pytest` on screen for 3 seconds.

## 2:05 - 2:40  Moment 3: Nightshift + Nemotron (terminal + Nightshift console)
Run the contract cliff. Show the trace line from the Writer: `"model":
"nvidia/nemotron-3.5-lightning-30b-a3b"`, `receipt_id`. Show the Nightshift window with the
NVIDIA provider connected. Read the numbers: 173 contracts, GBP 22.7m, no extension date recorded past vesting day
past vesting day; the largest, GBP 8.5m, ends 13 days after vesting day. Show the drafted
novation letter held as draft-1, status pending - "not sent".

## 2:40 - 3:00  Policy gap and close (terminal + slide)
Run the policy gap. Show the four differing clauses with page numbers: capital limit
10,000 vs 6,000; minimum award 5 vs 10; backdating 6 months vs 1 month; bands F-H excluded
in Guildford. "Four of eight synthetic residents - labelled synthetic - get a different
answer on day one. That is what the shadow authority has to decide before the 2027/28
bills."
Close: "Fresh clone, no credentials, SAMPLE_MODE: the same agents on the same data. Repo
link on screen."

## Frame checks before recording
- No token, key or password visible: Nightshift Console cropped to the URL line; the .env
  never on screen; the Zetaris API keys page never on screen.
- Trace lines readable: terminal font 16+, width 120.
- Every number spoken matches the output on screen.
