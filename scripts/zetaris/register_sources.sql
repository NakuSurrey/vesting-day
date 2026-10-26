-- Register the three council databases in Zetaris as three separate sources.
-- Run in the Zetaris SQL Editor (http://localhost:3000 through the SSH tunnel) as the
-- admin, ONE statement at a time - the editor splits on semicolons.
--
-- Replace __VD_READER_PASSWORD__ with the password in /root/vd_reader.pw on the server
-- (docs/ZETARIS_SETUP.md, step 2). Never commit it. vd_reader can only read.
--
-- "vd-postgres" is the database container's name on the zetaris_default Docker network,
-- so Zetaris reaches it by that name. It publishes no port, so nothing on the internet can.

CREATE DATASOURCE woking_pg DESCRIBE BY "Woking Borough Council - published spend, contracts, CTS clauses" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://vd-postgres:5432/vd_woking",
  username "vd_reader",
  password "__VD_READER_PASSWORD__",
  fetchsize "1000"
);

CREATE DATASOURCE guildford_pg DESCRIBE BY "Guildford Borough Council - published spend, contracts, CTR clauses" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://vd-postgres:5432/vd_guildford",
  username "vd_reader",
  password "__VD_READER_PASSWORD__",
  fetchsize "1000"
);

CREATE DATASOURCE waverley_pg DESCRIBE BY "Waverley Borough Council - published spend and contracts" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://vd-postgres:5432/vd_waverley",
  username "vd_reader",
  password "__VD_READER_PASSWORD__",
  fetchsize "1000"
);

REGISTER DATASOURCE TABLES ('spend', 'contracts', 'policy_clause') FROM woking_pg;
REGISTER DATASOURCE TABLES ('spend', 'contracts', 'policy_clause') FROM guildford_pg;
REGISTER DATASOURCE TABLES ('spend', 'contracts', 'policy_clause') FROM waverley_pg;

-- Smoke test - one federated query across all three sources (expect 9718 / 6883 / 3246):
-- SELECT 'Woking' AS council, COUNT(*) AS spend_rows FROM woking_pg.spend
-- UNION ALL SELECT 'Guildford', COUNT(*) FROM guildford_pg.spend
-- UNION ALL SELECT 'Waverley', COUNT(*) FROM waverley_pg.spend
