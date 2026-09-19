from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config.settings import Settings
from app.judge.schemas import JudgeDecisionRecord
from app.risk.correlation import (
    compute_correlation_matrix,
    compute_daily_returns,
    flag_concentrated_pairs,
    pearson_correlation,
)
from app.risk.engine import RiskEngine, SizedDecision


# --- correlation math ---------------------------------------------------------

def test_compute_daily_returns():
    returns = compute_daily_returns([100, 110, 99])
    assert returns == pytest.approx([0.10, -0.10], abs=1e-9)


def test_pearson_correlation_perfectly_correlated():
    a = [100, 110, 121, 133.1]
    b = [50, 55, 60.5, 66.55]  # exact scalar multiple -> corr == 1.0
    assert pearson_correlation(compute_daily_returns(a), compute_daily_returns(b)) == pytest.approx(1.0)


def test_pearson_correlation_uncorrelated_or_insufficient_data():
    assert pearson_correlation([0.1], [0.2]) is None  # too few points
    assert pearson_correlation([0.0, 0.0, 0.0], [0.1, -0.1, 0.2]) is None  # zero variance


def test_flag_concentrated_pairs_threshold():
    matrix = {("BTC", "ETH"): 0.9, ("BTC", "XRP"): 0.3}
    flagged = flag_concentrated_pairs(matrix, threshold=0.7)
    assert flagged == [("BTC", "ETH", 0.9)]


# --- RiskEngine: confidence gating --------------------------------------------

def _decision(**overrides):
    defaults = dict(
        run_id="RUN-1", asset_id="a1", created_at=datetime.now(UTC), decision="BUY",
        confidence=0.7, target_allocation=0.10, expected_return=0.15, expected_alpha=0.08,
        risk_score=0.4, uncertainty=0.3, model_agreement=0.9, source_agreement=0.9,
        investment_horizon_days=30, key_evidence=[], contradictory_evidence=[], key_risks=[],
        invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity="n/a", regime_id="r1",
        prompt_template_id="p1", estimated_cost=Decimal("0.01"),
    )
    defaults.update(overrides)
    return JudgeDecisionRecord(**defaults)


def _engine(**settings_overrides):
    defaults = dict(_env_file=None)
    defaults.update(settings_overrides)
    return RiskEngine(Settings(**defaults))


def test_low_confidence_buy_downgraded_to_watch():
    engine = _engine(min_buy_confidence=0.55)
    sized = engine.size_one(_decision(decision="BUY", confidence=0.3), "BTC", 0.02, 0.0, 0.0)
    assert sized.decision == "WATCH"
    assert sized.original_decision == "BUY"


def test_low_confidence_sell_downgraded_to_hold():
    engine = _engine(min_sell_confidence=0.55)
    sized = engine.size_one(_decision(decision="SELL", confidence=0.3), "BTC", 0.02, 0.10, 0.10)
    assert sized.decision == "HOLD"


def test_high_confidence_buy_passes_gate():
    engine = _engine(min_buy_confidence=0.55)
    sized = engine.size_one(_decision(decision="BUY", confidence=0.8), "BTC", 0.02, 0.0, 0.0)
    assert sized.decision == "BUY"


def test_sell_zeroes_allocation():
    engine = _engine(min_sell_confidence=0.3)
    sized = engine.size_one(_decision(decision="SELL", confidence=0.7), "BTC", 0.02, 0.10, 0.10)
    assert sized.final_allocation == 0.0


def test_watch_and_no_trade_never_change_current_allocation():
    # Below max_single_asset_allocation (default 0.15): the target simply
    # tracks real holdings, unchanged. See the
    # "RiskEngine: WATCH/NO_TRADE target-allocation cap" section below for
    # the above-cap clamp behavior.
    engine = _engine()
    sized = engine.size_one(_decision(decision="WATCH"), "BTC", 0.02, 0.05, 0.05)
    assert sized.final_allocation == 0.05
    sized2 = engine.size_one(_decision(decision="NO_TRADE"), "BTC", 0.02, 0.05, 0.05)
    assert sized2.final_allocation == 0.05


# --- RiskEngine: WATCH/NO_TRADE target-allocation cap -------------------------
#
# Real bug fixed 2026-09-16 (see doc/history.md's Phase 5g section): WATCH/
# NO_TRADE's `final_allocation = current_allocation` passthrough had no
# `max_single_asset_allocation` check at all, so real holdings sitting
# above the cap could be silently re-adopted as the system's own target,
# undoing a prior turnover-costly REDUCE for free. The fix bounds only the
# DESIRED TARGET this branch expresses -- `current_allocation` (real
# holdings) is never touched, and the fix is entirely local to this one
# branch (SELL and BUY/HOLD-resize sizing are unaffected).

def test_watch_target_below_cap_is_unaffected():
    engine = _engine(max_single_asset_allocation=0.15)
    sized = engine.size_one(_decision(decision="WATCH"), "BTC", 0.02, current_allocation=0.10, previous_system_target=0.10)
    assert sized.final_allocation == pytest.approx(0.10)
    assert sized.current_allocation == pytest.approx(0.10)  # real holdings untouched


def test_watch_target_exactly_at_cap_is_unaffected():
    engine = _engine(max_single_asset_allocation=0.15)
    sized = engine.size_one(_decision(decision="WATCH"), "BTC", 0.02, current_allocation=0.15, previous_system_target=0.15)
    assert sized.final_allocation == pytest.approx(0.15)
    assert sized.current_allocation == pytest.approx(0.15)


def test_watch_target_above_cap_is_clamped_to_the_cap():
    engine = _engine(max_single_asset_allocation=0.15)
    sized = engine.size_one(_decision(decision="WATCH"), "BTC", 0.02, current_allocation=0.33, previous_system_target=0.33)
    assert sized.final_allocation == pytest.approx(0.15)
    # Real holdings are reported completely unchanged -- this decision
    # never touches actual exposure, only the desired target.
    assert sized.current_allocation == pytest.approx(0.33)


def test_no_trade_decision_value_directly_clamps_to_cap():
    engine = _engine(max_single_asset_allocation=0.15)
    sized = engine.size_one(_decision(decision="NO_TRADE"), "BTC", 0.02, current_allocation=0.33, previous_system_target=0.33)
    assert sized.decision == "NO_TRADE"
    assert sized.final_allocation == pytest.approx(0.15)
    assert sized.current_allocation == pytest.approx(0.33)


def test_watch_clamp_does_not_count_as_strategy_turnover():
    # The resulting (clamped) target may still be subject to the existing
    # turnover mechanism downstream -- but WATCH/NO_TRADE's own turnover
    # delta stays hard-zero regardless of the clamp (unchanged,
    # pre-existing behavior -- see _strategy_turnover_delta), so
    # apply_turnover_cap must neither charge nor revert it.
    engine = _engine(max_single_asset_allocation=0.15, max_weekly_turnover=0.0)
    sized = engine.size_one(_decision(decision="WATCH"), "BTC", 0.02, current_allocation=0.33, previous_system_target=0.1632)
    assert sized.final_allocation == pytest.approx(0.15)

    engine.apply_turnover_cap([sized], turnover_used_this_week=0.0)  # zero budget remaining

    assert sized.final_allocation == pytest.approx(0.15)  # untouched by the turnover cap
    assert sized.turnover_capped is False


def test_reduce_then_watch_does_not_restore_the_target_above_the_cap():
    # Reproduces the real 2026-09-13 -> 2026-09-15 BTC incident
    # conceptually (real percentages differ -- this project's cap has
    # changed over time; what matters is the STRUCTURE of the bug): a
    # REDUCE (BUY/HOLD-resize branch) genuinely lowers the desired target;
    # real holdings never move (no real sell executes); a subsequent WATCH
    # must settle at the cap, never silently jump back up toward real
    # holdings the way it did before this fix.
    engine = _engine(max_single_asset_allocation=0.15, max_new_position_size=1.0)
    real_holdings = 0.33  # never resolves -- no real sell ever executes in this scenario

    reduce_decision = _decision(decision="HOLD", target_allocation=0.10, model_agreement=1.0, source_agreement=1.0)
    reduced = engine.size_one(reduce_decision, "BTC", None, current_allocation=real_holdings, previous_system_target=0.20)
    assert reduced.final_allocation == pytest.approx(0.10)  # the REDUCE takes effect, well under the cap

    watch_decision = _decision(decision="WATCH")
    watched = engine.size_one(watch_decision, "BTC", None, current_allocation=real_holdings, previous_system_target=reduced.final_allocation)
    # The old bug: this would be 0.33 (real holdings), silently undoing the
    # REDUCE and jumping straight past the cap in one free step.
    assert watched.final_allocation == pytest.approx(0.15)
    assert watched.final_allocation < real_holdings
    assert watched.current_allocation == pytest.approx(real_holdings)  # real holdings still reported, untouched


# --- RiskEngine: A2 cap-compliance correction (2026-09-17) --------------------
#
# A BUY/HOLD/SELL decision that reduces a genuinely oversized
# previous_system_target down to, or below, MAX_SINGLE_ASSET_ALLOCATION is
# exempted from MAX_WEEKLY_TURNOVER the same way WATCH/NO_TRADE (A1) already
# are -- both are the system correcting itself back within an already-
# enforced hard constraint, not discretionary strategy churn. See
# is_cap_compliance_correction's own docstring and doc/decisions.md's A2
# entry for the full reasoning.

def test_normal_compliant_buy_hold_is_not_a2():
    # previous_system_target is not oversized -- ordinary strategy turnover.
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized("a1", "BTC", "HOLD", current_allocation=0.10, previous_system_target=0.10, final_allocation=0.12)
    assert engine._strategy_turnover_delta(d) == pytest.approx(0.02)


def test_oversized_target_reduced_to_exactly_the_cap_is_exempt():
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized("a1", "BTC", "HOLD", current_allocation=0.30, previous_system_target=0.30, final_allocation=0.15)
    assert engine._strategy_turnover_delta(d) == 0.0


def test_oversized_previous_target_reduced_below_cap_is_exempt():
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized("a1", "BTC", "HOLD", current_allocation=0.30, previous_system_target=0.30, final_allocation=0.10)
    assert engine._strategy_turnover_delta(d) == 0.0


def test_sell_to_zero_from_oversized_target_is_exempt():
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized("a1", "BTC", "SELL", current_allocation=0.30, previous_system_target=0.30, final_allocation=0.0)
    assert engine._strategy_turnover_delta(d) == 0.0


def test_a1_watch_no_trade_unaffected_by_a2():
    # A1 regression: WATCH/NO_TRADE must still be zero, via A1's own,
    # completely separate condition -- unaffected by the new A2 predicate.
    engine = _engine(max_single_asset_allocation=0.15)
    watch = _sized("a1", "BTC", "WATCH", current_allocation=0.30, previous_system_target=0.30, final_allocation=0.15)
    no_trade = _sized("a2", "ETH", "NO_TRADE", current_allocation=0.30, previous_system_target=0.30, final_allocation=0.15)
    assert engine._strategy_turnover_delta(watch) == 0.0
    assert engine._strategy_turnover_delta(no_trade) == 0.0


def test_final_target_still_above_cap_does_not_trigger_a2():
    # Protects the predicate from silently treating EVERY reduction of an
    # oversized position as risk-control -- only a reduction that actually
    # reaches compliance qualifies.
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized("a1", "BTC", "HOLD", current_allocation=0.30, previous_system_target=0.30, final_allocation=0.20)
    assert engine._strategy_turnover_delta(d) == pytest.approx(-0.10)


def test_previous_target_exactly_at_cap_does_not_trigger_a2():
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized("a1", "BTC", "HOLD", current_allocation=0.15, previous_system_target=0.15, final_allocation=0.10)
    assert engine._strategy_turnover_delta(d) == pytest.approx(-0.05)


def test_epsilon_boundary_previous_target_not_qualifying_just_above_cap():
    from app.risk.engine import TURNOVER_EPSILON
    # previous_system_target sits within TURNOVER_EPSILON of the cap --
    # reused, not a new constant -- so this must NOT qualify as oversized.
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized(
        "a1", "BTC", "HOLD", current_allocation=0.15, previous_system_target=0.15 + TURNOVER_EPSILON / 2,
        final_allocation=0.10,
    )
    assert engine._strategy_turnover_delta(d) == pytest.approx(-0.05 - TURNOVER_EPSILON / 2)


def test_epsilon_boundary_previous_target_qualifying_just_beyond_epsilon():
    from app.risk.engine import TURNOVER_EPSILON
    engine = _engine(max_single_asset_allocation=0.15)
    d = _sized(
        "a1", "BTC", "HOLD", current_allocation=0.15, previous_system_target=0.15 + TURNOVER_EPSILON * 2,
        final_allocation=0.10,
    )
    assert engine._strategy_turnover_delta(d) == 0.0


def test_mixed_batch_a2_correction_does_not_consume_ordinary_strategy_budget():
    # BTC: oversized target -> compliant HOLD (A2, exempt).
    # ADA: ordinary BUY, competing for a small remaining strategy budget.
    # The BTC correction must not enter proposed_turnover at all -- ADA's
    # scaling must be computed as if BTC weren't in the batch.
    engine = _engine(max_single_asset_allocation=0.15, max_weekly_turnover=1.0)
    btc = _sized("btc", "BTC", "HOLD", current_allocation=0.333, previous_system_target=0.30, final_allocation=0.15)
    ada = _sized("ada", "ADA", "BUY", current_allocation=0.05, previous_system_target=0.05, final_allocation=0.10)

    engine.apply_turnover_cap([btc, ada], turnover_used_this_week=0.99)  # remaining = 0.01

    assert btc.final_allocation == pytest.approx(0.15)  # A2 correction proceeds in full
    assert btc.turnover_capped is False
    assert ada.final_allocation == pytest.approx(0.05 + 0.05 * (0.01 / 0.05))  # scaled using ONLY its own demand
    assert ada.turnover_capped is True


def test_multiple_simultaneous_a2_corrections_all_proceed_with_no_ordering():
    engine = _engine(max_single_asset_allocation=0.15, max_weekly_turnover=0.0)  # zero strategy budget
    btc = _sized("btc", "BTC", "HOLD", current_allocation=0.333, previous_system_target=0.30, final_allocation=0.15)
    eth = _sized("eth", "ETH", "HOLD", current_allocation=0.28, previous_system_target=0.25, final_allocation=0.15)
    sol = _sized("sol", "SOL", "SELL", current_allocation=0.22, previous_system_target=0.20, final_allocation=0.0)

    engine.apply_turnover_cap([btc, eth, sol], turnover_used_this_week=0.0)  # remaining = 0

    assert btc.final_allocation == pytest.approx(0.15)
    assert eth.final_allocation == pytest.approx(0.15)
    assert sol.final_allocation == pytest.approx(0.0)
    assert btc.turnover_capped is False
    assert eth.turnover_capped is False
    assert sol.turnover_capped is False


def test_a2_correction_does_not_repeat_once_compliant():
    # Repeated application / convergence: once the target is compliant, a
    # subsequent identical-shaped decision no longer qualifies (previous ==
    # final, or previous no longer oversized) -- mirrors A1's own proven
    # idempotency (test_reduce_then_watch_does_not_restore_the_target_above_the_cap).
    engine = _engine(max_single_asset_allocation=0.15)
    corrected = _sized("a1", "BTC", "HOLD", current_allocation=0.333, previous_system_target=0.15, final_allocation=0.15)
    assert engine._strategy_turnover_delta(corrected) == 0.0  # no movement at all -- not an A2 case, just a no-op


# --- RiskEngine: volatility-adjusted sizing -----------------------------------

def test_higher_volatility_asset_gets_smaller_position_at_equal_confidence():
    engine = _engine(risk_target_volatility=0.03, max_single_asset_allocation=1.0, max_new_position_size=1.0)
    low_vol = engine.size_one(_decision(target_allocation=0.10), "LOWVOL", 0.02, 0.0, 0.0)
    high_vol = engine.size_one(_decision(target_allocation=0.10), "HIGHVOL", 0.08, 0.0, 0.0)
    assert low_vol.final_allocation > high_vol.final_allocation


def test_volatility_scalar_never_scales_above_one():
    engine = _engine(risk_target_volatility=0.03, max_single_asset_allocation=1.0, max_new_position_size=1.0)
    very_low_vol = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=1.0, source_agreement=1.0), "STABLE", 0.001, 0.0, 0.0
    )
    assert very_low_vol.vol_scalar == 1.0
    assert very_low_vol.final_allocation == pytest.approx(0.10)  # not levered up


def test_unknown_volatility_does_not_adjust():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=1.0)
    sized = engine.size_one(_decision(target_allocation=0.10), "UNKNOWN", None, 0.0, 0.0)
    assert sized.vol_scalar == 1.0


# --- RiskEngine: uncertainty/agreement-aware scaling --------------------------

def test_weak_agreement_shrinks_position_at_equal_confidence_and_volatility():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=1.0)
    strong_agreement = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=1.0, source_agreement=1.0), "BTC", 0.02, 0.0, 0.0
    )
    weak_agreement = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=0.3, source_agreement=0.3), "BTC", 0.02, 0.0, 0.0
    )
    assert strong_agreement.final_allocation > weak_agreement.final_allocation


def test_agreement_scalar_has_a_floor():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=1.0)
    sized = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=0.0, source_agreement=0.0), "BTC", 0.02, 0.0, 0.0
    )
    assert sized.agreement_scalar == pytest.approx(0.3)


# --- RiskEngine: hard caps -----------------------------------------------------

def test_max_single_asset_allocation_caps_position():
    engine = _engine(max_single_asset_allocation=0.05, max_new_position_size=1.0)
    sized = engine.size_one(_decision(target_allocation=0.50), "BTC", 0.02, 0.05, 0.05)  # not a new position
    assert sized.final_allocation <= 0.05


def test_max_new_position_size_caps_initial_buy():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=0.02)
    sized = engine.size_one(_decision(target_allocation=0.50), "BTC", 0.02, 0.0, 0.0)  # new position
    assert sized.is_new_position is True
    assert sized.final_allocation <= 0.02


# --- RiskEngine: correlation-awareness ----------------------------------------

def test_correlation_flag_triggers_on_concentrated_scenario():
    engine = _engine()
    btc = SizedDecision(
        asset_id="a1", symbol="BTC", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, previous_system_target=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    alt = SizedDecision(
        asset_id="a2", symbol="ALT", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, previous_system_target=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    unrelated = SizedDecision(
        asset_id="a3", symbol="STABLECOIN_LIKE", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, previous_system_target=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    # BTC and ALT move in lockstep (perfectly correlated); the third asset is
    # anti-correlated with both, and should not be flagged.
    returns_by_symbol = {
        "BTC": [0.05, -0.02, 0.03, 0.01, -0.01],
        "ALT": [0.10, -0.04, 0.06, 0.02, -0.02],
        "STABLECOIN_LIKE": [-0.05, 0.02, -0.03, -0.01, 0.01],
    }

    engine.flag_correlations([btc, alt, unrelated], returns_by_symbol)

    assert btc.correlation_flagged is True
    assert alt.correlation_flagged is True
    assert unrelated.correlation_flagged is False


def test_correlation_flag_does_not_trigger_on_diversified_scenario():
    engine = _engine(correlation_flag_threshold=0.99)
    a = SizedDecision(
        asset_id="a1", symbol="BTC", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, previous_system_target=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    b = SizedDecision(
        asset_id="a2", symbol="ALT", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, previous_system_target=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    returns_by_symbol = {"BTC": [0.05, -0.02, 0.03], "ALT": [-0.01, 0.04, -0.02]}
    engine.flag_correlations([a, b], returns_by_symbol)
    assert a.correlation_flagged is False
    assert b.correlation_flagged is False


# --- RiskEngine: turnover cap ---------------------------------------------------
#
# The turnover baseline is `previous_system_target` (the strategy's own last
# recorded target), never `current_allocation` (real, ground-truth holdings)
# -- a real bug fixed 2026-09-14, see RiskEngine._strategy_turnover_delta's
# own docstring for the full incident and backtest evidence. Every test
# below that isn't specifically about a manual/external drift scenario sets
# `previous_system_target == current_allocation` (no drift), so the turnover
# math reduces to exactly the pre-fix numbers for these baseline mechanics.

def _sized(asset_id, symbol, decision, current_allocation, previous_system_target, final_allocation, **overrides):
    defaults = dict(
        asset_id=asset_id, symbol=symbol, decision=decision, original_decision=decision, confidence=0.7,
        current_allocation=current_allocation, previous_system_target=previous_system_target,
        final_allocation=final_allocation, vol_scalar=1.0, agreement_scalar=1.0, is_new_position=False,
    )
    defaults.update(overrides)
    return SizedDecision(**defaults)


def test_turnover_cap_scales_down_when_budget_exceeded():
    engine = _engine(max_weekly_turnover=0.10)
    a = _sized("a1", "BTC", "BUY", 0.0, 0.0, 0.10, is_new_position=True)
    b = _sized("a2", "ETH", "BUY", 0.0, 0.0, 0.10, is_new_position=True)
    # Proposed turnover = 0.20, but the full weekly budget (0.10) is
    # untouched so far this week.
    engine.apply_turnover_cap([a, b], turnover_used_this_week=0.0)

    assert a.turnover_capped is True
    assert b.turnover_capped is True
    assert (a.final_allocation + b.final_allocation) == pytest.approx(0.10)


def test_turnover_cap_blocks_everything_when_budget_already_spent():
    engine = _engine(max_weekly_turnover=0.10)
    a = _sized("a1", "BTC", "BUY", 0.05, 0.05, 0.10)  # no manual drift: current == previous target
    engine.apply_turnover_cap([a], turnover_used_this_week=0.10)
    assert a.final_allocation == 0.05  # reverted to the strategy's own previous target
    assert a.turnover_capped is True


def test_turnover_cap_no_op_when_under_budget():
    engine = _engine(max_weekly_turnover=1.0)
    a = _sized("a1", "BTC", "BUY", 0.0, 0.0, 0.05, is_new_position=True)
    engine.apply_turnover_cap([a], turnover_used_this_week=0.0)
    assert a.final_allocation == 0.05
    assert a.turnover_capped is False


def test_remaining_turnover_budget_matches_the_value_apply_turnover_cap_reasons_from():
    # Exposed so a caller (e.g. logging a TurnoverCapEvent) reports the
    # exact same number apply_turnover_cap itself used, not a separately
    # recomputed value that could silently drift from it.
    engine = _engine(max_weekly_turnover=0.3)
    assert engine.remaining_turnover_budget(0.30000000000000004) == 0.0
    assert engine.remaining_turnover_budget(0.1) == pytest.approx(0.2)


def test_turnover_cap_not_falsely_triggered_by_float_noise_at_exact_budget():
    # Real incident (2026-09-14): a week whose true turnover was exactly at
    # MAX_WEEKLY_TURNOVER computed as 0.30000000000000004 (summing real
    # portfolio_allocation_changes rows) against a 0.3 cap -- remaining
    # budget is genuinely ~0, not meaningfully negative. The fix doesn't
    # change THIS outcome (zero real room really means zero real room) --
    # it proves the epsilon-snap reaches that same zero-budget branch via a
    # real zero-budget determination, not by silently tolerating a larger
    # genuine overage.
    engine = _engine(max_weekly_turnover=0.3)
    a = _sized("a1", "ETH", "BUY", 0.0, 0.0, 0.13, confidence=0.6, is_new_position=True)
    engine.apply_turnover_cap([a], turnover_used_this_week=0.30000000000000004)
    assert a.final_allocation == 0.0  # reverted -- real budget is genuinely exhausted
    assert a.turnover_capped is True


def test_turnover_cap_snaps_near_zero_remaining_budget_to_avoid_dust_sized_changes():
    # A remaining budget that's a tiny POSITIVE float (well within
    # TURNOVER_EPSILON of zero) must be treated as genuinely exhausted --
    # without the snap, the old code would instead scale the proposed
    # change down to an economically meaningless dust-sized position
    # (e.g. ~1e-11) and still write that to the DB as a "real" allocation
    # change, rather than a clean, exact revert to the current allocation.
    engine = _engine(max_weekly_turnover=0.3)
    a = _sized("a1", "ETH", "BUY", 0.0, 0.0, 0.13, confidence=0.6, is_new_position=True)
    # remaining_budget = 0.3 - (0.3 - 1e-11) = 1e-11, well within epsilon.
    engine.apply_turnover_cap([a], turnover_used_this_week=0.3 - 1e-11)
    assert a.final_allocation == 0.0  # exact revert, not a ~1e-11-scaled dust position
    assert a.turnover_capped is True


# --- RiskEngine: turnover baseline (2026-09-14 fix) ---------------------------

def test_turnover_normal_rebalance_10_to_25_is_15pp():
    engine = _engine(max_weekly_turnover=1.0)
    a = _sized("a1", "BTC", "BUY", 0.10, 0.10, 0.25)  # no manual drift
    delta = engine._strategy_turnover_delta(a)
    assert delta == pytest.approx(0.15)


def test_turnover_decrease_25_to_10_is_15pp():
    # previous_system_target (0.15) is deliberately AT, not above, the
    # default cap -- a previous target above cap would make this an A2
    # cap-compliance correction (exempted, delta 0), which is not what
    # this test is checking (plain decrease-magnitude math, unrelated to
    # A2 -- see test_oversized_previous_target_reduced_below_cap_is_exempt).
    engine = _engine(max_weekly_turnover=1.0)
    a = _sized("a1", "BTC", "SELL", 0.15, 0.15, 0.0)
    delta = engine._strategy_turnover_delta(a)
    assert abs(delta) == pytest.approx(0.15)


def test_turnover_no_cross_asset_netting():
    # BTC +10pp, ETH -10pp -- must sum to 20pp, never net to 0.
    engine = _engine(max_weekly_turnover=1.0)
    btc = _sized("a1", "BTC", "BUY", 0.0, 0.0, 0.10, is_new_position=True)
    eth = _sized("a2", "ETH", "SELL", 0.10, 0.10, 0.0)
    total = sum(abs(engine._strategy_turnover_delta(d)) for d in (btc, eth))
    assert total == pytest.approx(0.20)


def test_turnover_bootstrap_first_position_counts_as_real_turnover():
    # Section 2C: initial construction is genuine turnover with real risk
    # implications (unlike external/manual drift below) -- no exemption.
    engine = _engine(max_weekly_turnover=1.0)
    a = _sized("a1", "BTC", "BUY", 0.0, 0.0, 0.10, is_new_position=True)
    assert engine._strategy_turnover_delta(a) == pytest.approx(0.10)


def test_turnover_manual_external_trade_is_not_charged_as_strategy_turnover():
    # The real 2026-09-14 incident, reproduced exactly: system target was
    # 10%, a manual /holdings trade pushed REAL holdings to 30%, and the
    # Judge's own next recommendation (independent of the manual trade)
    # works out to a final_allocation of 12% -- a genuine, small 2pp
    # strategy move. Under the OLD (real-holdings) baseline this would have
    # been mis-measured as an 18pp change (0.30 -> 0.12). Under the fix, it
    # must measure only the real 2pp the strategy itself decided.
    engine = _engine(max_weekly_turnover=1.0)
    a = _sized("a1", "BTC", "BUY", current_allocation=0.30, previous_system_target=0.10, final_allocation=0.12)
    delta = engine._strategy_turnover_delta(a)
    assert delta == pytest.approx(0.02)  # NOT abs(0.12 - 0.30) == 0.18


def test_turnover_watch_and_no_trade_never_count_even_with_real_drift():
    # A WATCH/NO_TRADE call is explicitly not a sizing decision (per
    # PHASE3E_PROMPT.md) -- it must contribute zero strategy turnover
    # regardless of how far real holdings have drifted from the system's
    # own target.
    engine = _engine(max_weekly_turnover=1.0)
    watch = _sized("a1", "BTC", "WATCH", current_allocation=0.30, previous_system_target=0.10, final_allocation=0.30)
    no_trade = _sized("a2", "ETH", "NO_TRADE", current_allocation=0.22, previous_system_target=0.05, final_allocation=0.22)
    assert engine._strategy_turnover_delta(watch) == 0.0
    assert engine._strategy_turnover_delta(no_trade) == 0.0


def test_turnover_cap_blocks_without_corrupting_target_under_real_drift():
    # Zero budget + a real manual-drift scenario: blocking must revert to
    # the strategy's own previous target, never to real holdings (which
    # would silently and incorrectly adopt the manual trade as the new
    # "official" target).
    engine = _engine(max_weekly_turnover=0.10)
    a = _sized("a1", "BTC", "BUY", current_allocation=0.30, previous_system_target=0.10, final_allocation=0.12)
    engine.apply_turnover_cap([a], turnover_used_this_week=0.10)
    assert a.final_allocation == 0.10  # reverted to previous_system_target, NOT 0.30
    assert a.turnover_capped is True


def test_turnover_cap_is_still_a_real_safety_control_10_to_50_with_30_remaining():
    # Exact audit scenario: previous target 10%, proposed new target 50%
    # (a real 40pp strategy move), with exactly 30% of budget remaining.
    # Must scale to exactly 30pp applied, not let the full 40pp through.
    engine = _engine(max_weekly_turnover=1.0)
    a = _sized("a1", "BTC", "BUY", current_allocation=0.10, previous_system_target=0.10, final_allocation=0.50)
    engine.apply_turnover_cap([a], turnover_used_this_week=0.70)  # 1.0 - 0.70 = 0.30 remaining
    assert a.final_allocation == pytest.approx(0.10 + 0.40 * (0.30 / 0.40))  # == 0.40
    assert a.final_allocation == pytest.approx(0.40)
    assert a.turnover_capped is True

    # Same proposed move, but budget is exactly exhausted (remaining=0) --
    # must block/revert to the PREVIOUS SYSTEM TARGET (0.10), never to
    # real holdings (which in this test happen to equal 0.10 too, so a
    # second case with divergent real holdings proves the point cleanly).
    engine2 = _engine(max_weekly_turnover=0.70)
    b = _sized("a1", "BTC", "BUY", current_allocation=0.85, previous_system_target=0.10, final_allocation=0.50)
    engine2.apply_turnover_cap([b], turnover_used_this_week=0.70)
    assert b.final_allocation == pytest.approx(0.10)  # previous_system_target, NOT 0.85 (real holdings)
    assert b.turnover_capped is True


def test_turnover_cap_scales_proportionally_using_previous_target_as_baseline_under_drift():
    # Slightly-above-cap scaling must interpolate from previous_system_target
    # toward the proposed final_allocation, not from real holdings.
    engine = _engine(max_weekly_turnover=0.01)
    a = _sized("a1", "BTC", "BUY", current_allocation=0.30, previous_system_target=0.10, final_allocation=0.12)
    engine.apply_turnover_cap([a], turnover_used_this_week=0.0)
    # raw strategy delta = 0.02, remaining budget = 0.01 -> scale = 0.5
    assert a.final_allocation == pytest.approx(0.10 + 0.02 * 0.5)
    assert a.turnover_capped is True


def test_turnover_manual_change_then_strategy_rebalance_still_uses_real_holdings_for_gating():
    # The system must still REACT to the real, changed holdings (risk
    # gating uses current_allocation, unaffected by this fix) while
    # correctly NOT charging the drift itself to the turnover budget. A
    # large real holding (not a "new position") should not be treated as
    # opening a fresh position just because the strategy's own target was 0.
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=0.02)
    sized = engine.size_one(
        _decision(decision="BUY", confidence=0.8, target_allocation=0.50),
        "BTC", 0.02, current_allocation=0.30, previous_system_target=0.0,
    )
    # is_new_position is real-holdings-based (you already really hold 30%)
    # -- max_new_position_size (0.02) must NOT apply here; only the
    # (much larger) vol/agreement-scaled sizing math applies.
    assert sized.is_new_position is False
    assert sized.final_allocation > 0.02
    assert sized.final_allocation == pytest.approx(0.45)  # 0.50 target * 1.0 vol * 0.9 agreement
    # ...but the turnover charged is still measured against the strategy's
    # own previous target (0.0 -> 0.45 = a real, large, correctly-counted
    # bootstrap-style move -- not further inflated or deflated by the real
    # holdings value).
    engine2 = _engine(max_weekly_turnover=1.0)
    assert engine2._strategy_turnover_delta(sized) == pytest.approx(0.45)
