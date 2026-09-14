-- Additive continuous complement to model_agreement's coarse discrete
-- majority-vote fraction (real observed history: only 1.0 or 0.667 ever
-- occur at n=3 models) -- see app/llm/assessment_agreement.py's
-- compute_return_dispersion and the dashboard's own
-- "[HIGH][AI] model_agreement" TODO. Real dispersion (population stdev) of
-- the models' own expected_return_30d figures, in the same return-fraction
-- units. NULL when only one model's response was usable (nothing to
-- compute a spread from), never fabricated as 0. Purely additive -- does
-- NOT replace model_agreement, which is unchanged and still the only
-- agreement figure fed into the Risk Engine's sizing scalar.
-- Idempotent -- safe to re-run.

alter table model_market_assessments
    add column if not exists expected_return_dispersion_30d numeric;
