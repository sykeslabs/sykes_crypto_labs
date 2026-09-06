-- Phase 3h task 1/1a: adaptive evidence-value ranking + drift detection.
-- `method` distinguishes the full-history run from rolling-window/regime-
-- sliced runs, so every attempt is a countable, reproducible event, same
-- convention as `calibration_runs` (3e/3g). Idempotent — safe to re-run.

create table if not exists evidence_value_reports (
    id                       uuid primary key default gen_random_uuid(),
    run_at                   timestamptz not null default now(),
    method                   text not null,
    sample_size              integer not null,
    decision_outcomes_window text,
    feature_importances      jsonb not null default '{}',
    sufficient_sample        boolean not null default false,
    notes                    text
);

create index if not exists idx_evidence_value_reports_method
    on evidence_value_reports (method);
