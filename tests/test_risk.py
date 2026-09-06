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
    sized = engine.size_one(_decision(decision="BUY", confidence=0.3), "BTC", 0.02, 0.0)
    assert sized.decision == "WATCH"
    assert sized.original_decision == "BUY"


def test_low_confidence_sell_downgraded_to_hold():
    engine = _engine(min_sell_confidence=0.55)
    sized = engine.size_one(_decision(decision="SELL", confidence=0.3), "BTC", 0.02, 0.10)
    assert sized.decision == "HOLD"


def test_high_confidence_buy_passes_gate():
    engine = _engine(min_buy_confidence=0.55)
    sized = engine.size_one(_decision(decision="BUY", confidence=0.8), "BTC", 0.02, 0.0)
    assert sized.decision == "BUY"


def test_sell_zeroes_allocation():
    engine = _engine(min_sell_confidence=0.3)
    sized = engine.size_one(_decision(decision="SELL", confidence=0.7), "BTC", 0.02, 0.10)
    assert sized.final_allocation == 0.0


def test_watch_and_no_trade_never_change_current_allocation():
    engine = _engine()
    sized = engine.size_one(_decision(decision="WATCH"), "BTC", 0.02, 0.05)
    assert sized.final_allocation == 0.05
    sized2 = engine.size_one(_decision(decision="NO_TRADE"), "BTC", 0.02, 0.05)
    assert sized2.final_allocation == 0.05


# --- RiskEngine: volatility-adjusted sizing -----------------------------------

def test_higher_volatility_asset_gets_smaller_position_at_equal_confidence():
    engine = _engine(risk_target_volatility=0.03, max_single_asset_allocation=1.0, max_new_position_size=1.0)
    low_vol = engine.size_one(_decision(target_allocation=0.10), "LOWVOL", 0.02, 0.0)
    high_vol = engine.size_one(_decision(target_allocation=0.10), "HIGHVOL", 0.08, 0.0)
    assert low_vol.final_allocation > high_vol.final_allocation


def test_volatility_scalar_never_scales_above_one():
    engine = _engine(risk_target_volatility=0.03, max_single_asset_allocation=1.0, max_new_position_size=1.0)
    very_low_vol = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=1.0, source_agreement=1.0), "STABLE", 0.001, 0.0
    )
    assert very_low_vol.vol_scalar == 1.0
    assert very_low_vol.final_allocation == pytest.approx(0.10)  # not levered up


def test_unknown_volatility_does_not_adjust():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=1.0)
    sized = engine.size_one(_decision(target_allocation=0.10), "UNKNOWN", None, 0.0)
    assert sized.vol_scalar == 1.0


# --- RiskEngine: uncertainty/agreement-aware scaling --------------------------

def test_weak_agreement_shrinks_position_at_equal_confidence_and_volatility():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=1.0)
    strong_agreement = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=1.0, source_agreement=1.0), "BTC", 0.02, 0.0
    )
    weak_agreement = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=0.3, source_agreement=0.3), "BTC", 0.02, 0.0
    )
    assert strong_agreement.final_allocation > weak_agreement.final_allocation


def test_agreement_scalar_has_a_floor():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=1.0)
    sized = engine.size_one(
        _decision(target_allocation=0.10, model_agreement=0.0, source_agreement=0.0), "BTC", 0.02, 0.0
    )
    assert sized.agreement_scalar == pytest.approx(0.3)


# --- RiskEngine: hard caps -----------------------------------------------------

def test_max_single_asset_allocation_caps_position():
    engine = _engine(max_single_asset_allocation=0.05, max_new_position_size=1.0)
    sized = engine.size_one(_decision(target_allocation=0.50), "BTC", 0.02, 0.05)  # not a new position
    assert sized.final_allocation <= 0.05


def test_max_new_position_size_caps_initial_buy():
    engine = _engine(max_single_asset_allocation=1.0, max_new_position_size=0.02)
    sized = engine.size_one(_decision(target_allocation=0.50), "BTC", 0.02, 0.0)  # new position
    assert sized.is_new_position is True
    assert sized.final_allocation <= 0.02


# --- RiskEngine: correlation-awareness ----------------------------------------

def test_correlation_flag_triggers_on_concentrated_scenario():
    engine = _engine()
    btc = SizedDecision(
        asset_id="a1", symbol="BTC", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    alt = SizedDecision(
        asset_id="a2", symbol="ALT", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    unrelated = SizedDecision(
        asset_id="a3", symbol="STABLECOIN_LIKE", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
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
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    b = SizedDecision(
        asset_id="a2", symbol="ALT", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    returns_by_symbol = {"BTC": [0.05, -0.02, 0.03], "ALT": [-0.01, 0.04, -0.02]}
    engine.flag_correlations([a, b], returns_by_symbol)
    assert a.correlation_flagged is False
    assert b.correlation_flagged is False


# --- RiskEngine: turnover cap ---------------------------------------------------

def test_turnover_cap_scales_down_when_budget_exceeded():
    engine = _engine(max_weekly_turnover=0.10)
    a = SizedDecision(
        asset_id="a1", symbol="BTC", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    b = SizedDecision(
        asset_id="a2", symbol="ETH", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    # Proposed turnover = 0.20, but the full weekly budget (0.10) is
    # untouched so far this week.
    engine.apply_turnover_cap([a, b], turnover_used_this_week=0.0)

    assert a.turnover_capped is True
    assert b.turnover_capped is True
    assert (a.final_allocation + b.final_allocation) == pytest.approx(0.10)


def test_turnover_cap_blocks_everything_when_budget_already_spent():
    engine = _engine(max_weekly_turnover=0.10)
    a = SizedDecision(
        asset_id="a1", symbol="BTC", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.05, final_allocation=0.10, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=False,
    )
    engine.apply_turnover_cap([a], turnover_used_this_week=0.10)
    assert a.final_allocation == 0.05  # reverted to current — no further change allowed
    assert a.turnover_capped is True


def test_turnover_cap_no_op_when_under_budget():
    engine = _engine(max_weekly_turnover=1.0)
    a = SizedDecision(
        asset_id="a1", symbol="BTC", decision="BUY", original_decision="BUY", confidence=0.7,
        current_allocation=0.0, final_allocation=0.05, vol_scalar=1.0, agreement_scalar=1.0,
        is_new_position=True,
    )
    engine.apply_turnover_cap([a], turnover_used_this_week=0.0)
    assert a.final_allocation == 0.05
    assert a.turnover_capped is False
