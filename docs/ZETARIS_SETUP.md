# Zetaris setup for VESTING DAY (live mode)

Zetaris runs on a 16 GB Linux server (Docker). The app runs on the laptop and reaches
Zetaris over an SSH tunnel, so `ZETARIS_REST_URL` stays `http://localhost:8888/api/v1.0`
exactly as the Participant Setup Guide documents.

## 1. Install Zetaris on the server

Follow the Zetaris portal's "Run locally" steps on the server: registry sign-in, unzip the
platform bundle, `./preflight.sh` (all PASS), set the admin email and password in the
bundle's `.env`, `docker compose pull`, `docker compose up -d`, `./verify.sh` (9/9).
Never run `docker compose down -v` (it deletes the data and the encryption keys).

## 2. Start the source database next to Zetaris

One Postgres container joins the `zetaris_default` network under the host name
`vd-postgres`, with three schemas (woking, guildford, waverley) - three separate sources
for Zetaris to federate. From the repo root on the server:

```bash
docker run -d --name vd-postgres --network zetaris_default --restart unless-stopped \
  -e POSTGRES_DB=vestingday -e POSTGRES_USER=vd -e POSTGRES_PASSWORD="$VD_PG_PASSWORD" \
  -p 127.0.0.1:5433:5432 postgres:16-alpine
export VD_PG_DSN="postgresql://vd:$VD_PG_PASSWORD@127.0.0.1:5433/vestingday"
docker exec -i vd-postgres psql -U vd -d vestingday < scripts/zetaris/schema.sql
uv run --group prep python scripts/zetaris/load_sources.py
```

`VD_PG_PASSWORD` is a value you choose in the shell for the session; it is not stored in
the repo. Expected load: woking spend 9718, guildford 6883, waverley 3246; contracts
221 / 179 / 101; policy clauses 9 / 9 / 0.

## 3. Register the three sources in Zetaris

Open the Zetaris UI (tunnel: `ssh -L 3000:localhost:3000 -L 8888:localhost:8888 root@<server>`
then http://localhost:3000), sign in as the admin, open the SQL Editor and run the
statements in `scripts/zetaris/register_sources.sql` one at a time, with the two
placeholders replaced by the Postgres user and password from step 2. Then the smoke test
at the bottom of that file should return three rows.

## 4. Create the API key

Zetaris UI -> your user menu -> API keys -> create. Copy it immediately (it may be shown
once) into the laptop's `.env` as `ZETARIS_API_KEY`. `ZETARIS_ORG_ID=1` on a local install.

## 5. Point the app at it

On the laptop, with the tunnel open:

```
ZETARIS_REST_URL=http://localhost:8888/api/v1.0
ZETARIS_ORG_ID=1
ZETARIS_API_KEY=<from step 4>
SAMPLE_MODE=false
```

Every `{spend}`, `{contracts}` and `{policy_clause}` placeholder in the Researcher's SQL is
rendered by `app/adapters/datalayer.py` as a UNION over `woking_pg`, `guildford_pg` and
`waverley_pg`, so one statement is answered by Zetaris querying all three sources in place.

## 6. Check

```bash
python run.py --query "Which suppliers do Woking, Guildford and Waverley share?"
```

The trace's `query_data_layer` lines should name `zetaris (federated query-in-place ...)`
and the `run_mode` artifact should say `live`.
