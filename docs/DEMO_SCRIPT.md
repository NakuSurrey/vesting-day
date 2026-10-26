# Demo video script (target 3:15, limit 1-4 minutes)

Track: Solving Fragmented Intelligence. File name: `OAH2026-VestingDay-FragmentedIntelligence-Demo.mp4`
(MP4, 1080p, 16:9, with narration). Everything on screen is a real run; waits may be cut, inputs
and outputs may not.

## Before recording (laptop)

1. SSH tunnel open in its own window: `ssh -N -L 8888:localhost:8888 -L 3000:localhost:3000 root@<server-ip>`.
2. Nightshift running with the NVIDIA provider connected. Crop it to the model and URL line;
   the token and the NVIDIA key never appear on screen.
3. `.env` is never opened on screen. Clear terminal history that could show a key. Terminal
   font 16+, width 120. Browser zoom 110-125%.
4. The page writes traces as `logs/trace-web-*.jsonl`; do not `git add` them.

## 0:00-0:20  Problem (title slide)

"Our entry is for Solving Fragmented Intelligence. On 1 April 2027 Woking, Guildford and
Waverley become one West Surrey council. Their data does not merge: each publishes spend on
its own cadence and schema, keeps its own contracts register and runs its own Council Tax
Support scheme. The finance lead of the shadow authority needs answers now, and the
migration takes years."

## 0:20-0:40  Solution (findings slide)

"VESTING DAY asks one question across all three councils' published data, in place, through
Zetaris. It finds the suppliers they share, the contracts that end around vesting day, and
the residents who get a different answer on day one - every number traced to the council's
own file - and it drafts the first actions for a person to approve. The data is the councils'
real published data; the eight test residents are synthetic and labelled so."

## 0:40-1:15  Agents and collaboration (architecture slide)

"Eight agents, and it is not a chain. For a broad question the Planner decides which checks to
run - in live mode Nemotron proposes the plan and the code validates it - delegates them, and
revises a step that cannot run as asked. The Researcher queries Zetaris. The Resolver scores
every supplier pair, and Nemotron only suggests matches - a person decides. The Critic sends
work back: pairs below the bar, and briefings that over-claim or leave out a remembered
decision. Memory is the Meterless H-MEM engine. Nothing leaves without the approval gate."

## 1:15-2:20  Live run (the web page at http://localhost:8000, live mode)

Start the server before recording (`uv run python run.py`) with the tunnel open and `.env` live,
and click "Reset demo memory" once off camera.

1. In the question box: `Confirm that 'Unit 4 Business Software Ltd' (Waverley) is the same
   supplier as 'Unit4 Business Software Ltd' (Guildford)` - "A person confirms one supplier
   pair. It is stored in H-MEM as mem-1."
2. Click the example "What are the biggest risks on vesting day?" and talk over the agent steps
   as they appear on the right: "The Planner asked Nemotron which checks this needs - there is
   the plan with its receipt. It delegates: contracts, suppliers, Council Tax Support. The
   Researcher queries all three councils through Zetaris. Memory recalls mem-1, the decision I
   just made. The Critic rejects 217 pairs below the bar, and here it rejects Nemotron's first
   draft for over-claiming - the retry passes. Two actions are drafted and held for approval."
3. Read the brief's headline numbers: 173 contracts / GBP 22.7m, 229 pairs shared with mem-1
   named, 4 of 9 clauses. Point at "held for approval, nothing sent".

If the live model happens not to bounce this time, say so and point at the committed
`logs/trace-live-03.jsonl` rejection instead: "here is the Critic catching 'confirmed as shared'
in a recorded live run."

## 2:20-2:45  Sponsor technology (trace + Nightshift)

Show one Writer trace line with `"model": "nvidia/nemotron-3.5-lightning-30b-a3b"` and its
`receipt_id`, then the Nightshift window (cropped).
"Zetaris is the single SQL access point to three separate council databases that are never
merged. Every model call goes through Meterless Nightshift to NVIDIA Nemotron, with a signed
receipt per call. Memory is our port of the Meterless H-MEM engine - 13 of 13 on the official
conformance tests. We built it with Claude Code."

## 2:45-3:15  Output and impact (the page, then slides)

Scroll to the contracts step in the brief: "173 contracts worth 22.7 million end around vesting
day with no extension date recorded past it. The largest, 8.5 million of temporary staff at
Guildford, ends 13 days after vesting day. A novation letter is drafted and held - not sent."
Then the policy slide: "4 of 9 Council Tax Support clauses differ - capital limit 10,000 versus
6,000 - and 4 of 8 synthetic test residents get a different answer on day one. That is the
decision the new council has to make before its first bills."
Close: "Clone it and run it with no credentials. Repo on screen."

## Checks before submitting the video

- 1-4 minutes; names the track and the user; shows a real run, the Planner choosing steps, the
  Critic sending work back, Zetaris and Nightshift calls in the trace, memory named, and the final output.
- No token, key or password visible anywhere. Every number spoken matches the screen.
- Hosted link opens in a private browser window and plays with audio; keep a backup copy.
