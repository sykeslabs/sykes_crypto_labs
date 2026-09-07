-- Drops signal_sources.enabled -- seeded in migration 0003, before any
-- source besides CoinGecko/News was actually built, so almost every row
-- defaulted to false. Nothing in the codebase ever gated real behavior on
-- it (confirmed by grep: the only read was the dashboard's own display of
-- "yes"/"no"), and nothing ever updated it as sources were later
-- implemented and their `status` moved to OK -- so it settled into
-- actively misleading dead data (e.g. Binance shows `status=OK`,
-- `enabled=false`, despite being a real, currently-used source) rather
-- than a real operator on/off switch. Removed rather than repaired,
-- since there was no real plan to wire it into actual gating logic.
--
-- Idempotent -- safe to re-run.

alter table signal_sources
    drop column if exists enabled;
