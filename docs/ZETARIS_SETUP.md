# Zetaris setup for VESTING DAY (live mode)

Zetaris runs on a 16 GB Linux server (Docker). The app runs on the laptop and reaches
Zetaris over an SSH tunnel, so `ZETARIS_REST_URL` stays `http://localhost:8888/api/v1.0`
exactly as the Participant Setup Guide documents.

## 1. Install Zetaris on the server

Follow the Zetaris portal's "Run locally" steps on the server: registry sign-in, unzip the
platform bundle, `./preflight.sh` (all PASS), set the admin email and password in the
bundle's `.env`, `docker compose pull`, `docker compose up -d`, `./verify.sh` (9/9).
Never run `docker compose down -v` (it deletes the data and the encryption keys).

## 2. Start the council databases next to Zetaris

Each council gets its own Postgres database - `vd_woking`, `vd_guildford`, `vd_waverley` -
in one small container named `vd-postgres` on the `zetaris_default` Docker network. They
stand in for each council's own system: loaded from the councils' published files, never
merged. The container publishes no port, so it can't be reached from the internet - only
the Zetaris containers on that Docker network can talk to it.

On the server:

```bash
(umask 077 && openssl rand -hex 16 > /root/vd_reader.pw)
docker run -d --name vd-postgres --network zetaris_default --restart unless-stopped \
  -e POSTGRES_USER=vd -e POSTGRES_PASSWORD="$(openssl rand -hex 24)" postgres:16-alpine
git clone --depth 1 https://github.com/NakuSurrey/vesting-day /root/vesting-day
cd /root/vesting-day
python3 scripts/zetaris/build_load_sql.py \
  | docker exec -i vd-postgres psql -U vd -d postgres -v reader_pw="$(cat /root/vd_reader.pw)"
```

- `/root/vd_reader.pw` holds the password for `vd_reader`, the read-only login Zetaris
  uses. Only root can read it, and it never goes in the repo.
- The `vd` admin password is random and never needed again - the load runs through
  `docker exec`.
- Nothing is installed on the server: the load script is plain Python 3.
- Expected output: vd_woking spend 9718, contracts 221, policy_clause 9; vd_guildford
  6883 / 179 / 9; vd_waverley 3246 / 101 / 0. Safe to run again.

## 3. Register the three sources in Zetaris

Open the Zetaris UI (tunnel: `ssh -L 3000:localhost:3000 -L 8888:localhost:8888 root@<server>`
then http://localhost:3000), sign in as the admin, open the SQL Editor and run the
statements in `scripts/zetaris/register_sources.sql` one at a time, with
`__VD_READER_PASSWORD__` replaced by the contents of `/root/vd_reader.pw`
(`cat /root/vd_reader.pw` in the SSH window). Then the smoke test at the bottom of that
file should return three rows.

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
