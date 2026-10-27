# Live run on the laptop (Nightshift + Zetaris)

SAMPLE_MODE needs none of this. The live run is how the committed traces in `logs/` were made:
real Zetaris federation and real Nemotron requests through Nightshift, with receipts.

## 1. Once: clone and install

```powershell
cd $env:USERPROFILE
git clone https://github.com/NakuSurrey/vesting-day
cd vesting-day
uv sync
```

## 2. Nightshift values

Open Nightshift -> Console (top right). Copy the Runtime URL and the Runtime token.
(If the Console does not open, the token is the one line in
`%LOCALAPPDATA%\ai.meterless.runtime\proxy-token` and the URL is `http://127.0.0.1:8088/v1`.)

Check the lane answers (replace TOKEN with the token; never paste the token anywhere else):

```powershell
curl.exe -s http://127.0.0.1:8088/v1/chat/completions -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d '{"model":"nvidia/nemotron-3.5-lightning-30b-a3b","messages":[{"role":"user","content":"Reply with exactly: VESTING DAY OK"}],"max_tokens":256,"reasoning_effort":"none"}'
```

Expect `"content":"VESTING DAY OK"` and a `meterless` receipt block naming the model.

## 3. Zetaris tunnel

In a second PowerShell window, keep this open for the whole session:

```powershell
ssh -N -L 8888:localhost:8888 -L 3000:localhost:3000 root@<server-ip>
```

## 4. .env

Copy `.env.example` to `.env` and fill in `METERLESS_RUNTIME_TOKEN`, `ZETARIS_API_KEY`;
set `SAMPLE_MODE=false`. Leave `METERLESS_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b`.

## 5. Run the three flows live

```powershell
uv run python run.py --reset-memory --run-id live-01 --query "Which suppliers do Woking, Guildford and Waverley share?" --out logs/response-live-01.json
uv run python run.py --run-id live-02 --query "Confirm that 'Unit 4 Business Software Ltd' (Waverley) is the same supplier as 'Unit4 Business Software Ltd' (Guildford)" --out logs/response-live-02.json
uv run python run.py --run-id live-03 --query "Which suppliers do Guildford and Waverley share?" --out logs/response-live-03.json
uv run python run.py --run-id live-04 --query "Which contracts end within six months of vesting day?" --out logs/response-live-04.json
uv run python run.py --run-id live-05 --query "Where do the Council Tax Support schemes differ between Woking and Guildford?" --out logs/response-live-05.json
```

`--out` writes each response to `logs\response-live-0N.json` as UTF-8 (a stderr line shows the
status and the summary head); the trace is written to `logs\trace-live-0N.jsonl`. Check a trace
line from the Writer shows `"model": "nvidia/nemotron-3.5-lightning-30b-a3b"` and a
`receipt_id`, a Researcher line names `zetaris`, and the live-03 summary names the recalled
decision (`resolved using decision mem-1`).

## 6. Commit the live traces

```powershell
git add logs/response-live-0*.json logs/trace-live-0*.jsonl
git commit -m "Add live traces: Zetaris federation and Nemotron via Nightshift"
git push
```

Only the `logs/response-live-0N.json` and `logs/trace-live-0N.jsonl` files are added; `.env` is
ignored by git and must never be committed. To re-commit a single run, add just its two files,
e.g. `git add logs/response-live-03.json logs/trace-live-03.jsonl`.

## 7. Server at the end

Zetaris can be stopped with `docker compose down` (no `-v`, which would delete the data).
