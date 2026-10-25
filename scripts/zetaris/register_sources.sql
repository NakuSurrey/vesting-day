-- Register the three council sources in Zetaris (Lightning SQL, one statement per call).
-- Run from the Zetaris SQL Editor on :3000 as an administrator, or with the
-- getting-started runner. Replace the two placeholders with the Postgres user
-- and password you chose for the vd-postgres container; do not commit them.
--
-- "vd-postgres" is the container name on the zetaris_default network, so the
-- Zetaris containers reach it by that host name.

CREATE DATASOURCE woking_pg DESCRIBE BY "Woking Borough Council - published spend, contracts, CTS clauses" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://vd-postgres:5432/vestingday?currentSchema=woking",
  username "__PG_USER__",
  password "__PG_PASSWORD__",
  fetchsize "1000"
);

CREATE DATASOURCE guildford_pg DESCRIBE BY "Guildford Borough Council - published spend, contracts, CTR clauses" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://vd-postgres:5432/vestingday?currentSchema=guildford",
  username "__PG_USER__",
  password "__PG_PASSWORD__",
  fetchsize "1000"
);

CREATE DATASOURCE waverley_pg DESCRIBE BY "Waverley Borough Council - published spend and contracts" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://vd-postgres:5432/vestingday?currentSchema=waverley",
  username "__PG_USER__",
  password "__PG_PASSWORD__",
  fetchsize "1000"
);

REGISTER DATASOURCE TABLES FROM woking_pg;
REGISTER DATASOURCE TABLES FROM guildford_pg;
REGISTER DATASOURCE TABLES FROM waverley_pg;

-- Smoke test (expect three rows, one per council):
-- SELECT 'Woking' AS council, COUNT(*) FROM woking_pg.spend
-- UNION ALL SELECT 'Guildford', COUNT(*) FROM guildford_pg.spend
-- UNION ALL SELECT 'Waverley', COUNT(*) FROM waverley_pg.spend
