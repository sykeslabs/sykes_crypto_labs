import pytest

from app.risk.stress_test import (
    CONTAGION_ALT_DRAWDOWN,
    CONTAGION_MAJOR_DRAWDOWN,
    AssetDrawdownInput,
    altcoin_contagion_scenario,
    historical_worst_drawdown_scenario,
    run_all_scenarios,
)


def test_historical_worst_drawdown_scenario_matches_known_hand_computation():
    # Known expected portfolio drawdown: 0.5*(-0.5) + 0.5*(-0.8) = -0.65 exactly.
    allocations = {"BTC": 0.5, "ALT1": 0.5}
    drawdown_inputs = {
        "BTC": AssetDrawdownInput(symbol="BTC", max_drawdown=-0.5, data_points=1000, start_date="2023-12-12", end_date="2026-09-06"),
        "ALT1": AssetDrawdownInput(symbol="ALT1", max_drawdown=-0.8, data_points=1000, start_date="2023-12-12", end_date="2026-09-06"),
    }
    result = historical_worst_drawdown_scenario(allocations, drawdown_inputs, max_stress_scenario_drawdown=0.9)
    assert result.portfolio_drawdown_pct == pytest.approx(-0.65)
    assert result.cvar_style_estimate_pct == pytest.approx(-0.65)
    assert result.flagged is False  # 0.65 < 0.9 threshold
    assert all(not r.is_proxy for r in result.asset_results)


def test_historical_worst_drawdown_scenario_flags_when_threshold_exceeded():
    allocations = {"BTC": 0.5, "ALT1": 0.5}
    drawdown_inputs = {
        "BTC": AssetDrawdownInput(symbol="BTC", max_drawdown=-0.5),
        "ALT1": AssetDrawdownInput(symbol="ALT1", max_drawdown=-0.8),
    }
    result = historical_worst_drawdown_scenario(allocations, drawdown_inputs, max_stress_scenario_drawdown=0.5)
    assert result.flagged is True  # 0.65 > 0.5 threshold


def test_historical_worst_drawdown_scenario_uses_btc_proxy_for_missing_asset():
    allocations = {"BTC": 0.5, "NEWTOKEN": 0.5}
    drawdown_inputs = {
        "BTC": AssetDrawdownInput(symbol="BTC", max_drawdown=-0.5),
        # NEWTOKEN has no entry at all -- genuinely no real data.
    }
    result = historical_worst_drawdown_scenario(allocations, drawdown_inputs, max_stress_scenario_drawdown=0.9)
    new_token_result = next(r for r in result.asset_results if r.symbol == "NEWTOKEN")
    assert new_token_result.is_proxy is True
    assert new_token_result.drawdown_pct == pytest.approx(-0.5)  # BTC's real drawdown used as proxy
    assert "proxy" in new_token_result.proxy_reason
    # Known hand computation: 0.5*(-0.5) + 0.5*(-0.5 proxy) = -0.5 exactly.
    assert result.portfolio_drawdown_pct == pytest.approx(-0.5)


def test_historical_worst_drawdown_scenario_flags_stale_data_without_treating_as_proxy():
    allocations = {"XMR": 1.0}
    drawdown_inputs = {
        "BTC": AssetDrawdownInput(symbol="BTC", max_drawdown=-0.5),
        "XMR": AssetDrawdownInput(
            symbol="XMR", max_drawdown=-0.67, is_stale=True,
            start_date="2021-05-27", end_date="2024-02-20",
        ),
    }
    result = historical_worst_drawdown_scenario(allocations, drawdown_inputs, max_stress_scenario_drawdown=0.9)
    xmr_result = result.asset_results[0]
    assert xmr_result.is_proxy is False  # real data, not a proxy -- just stale
    assert xmr_result.drawdown_pct == pytest.approx(-0.67)  # its own real (if stale) number is used
    assert "stale" in xmr_result.proxy_reason


def test_altcoin_contagion_scenario_matches_known_hand_computation():
    # BTC/ETH are majors (-0.50); everything else is alt-tier (-0.85).
    # Known expected: 0.5*(-0.50) + 0.5*(-0.85) = -0.675 exactly.
    allocations = {"BTC": 0.5, "ALT1": 0.5}
    result = altcoin_contagion_scenario(allocations, max_stress_scenario_drawdown=0.9)
    assert result.portfolio_drawdown_pct == pytest.approx(-0.675)
    btc_result = next(r for r in result.asset_results if r.symbol == "BTC")
    alt_result = next(r for r in result.asset_results if r.symbol == "ALT1")
    assert btc_result.drawdown_pct == pytest.approx(CONTAGION_MAJOR_DRAWDOWN)
    assert alt_result.drawdown_pct == pytest.approx(CONTAGION_ALT_DRAWDOWN)


def test_altcoin_contagion_scenario_flags_when_threshold_exceeded():
    result = altcoin_contagion_scenario({"ALT1": 1.0}, max_stress_scenario_drawdown=0.5)
    assert result.flagged is True  # 0.85 > 0.5


def test_run_all_scenarios_returns_both_named_scenarios():
    allocations = {"BTC": 1.0}
    drawdown_inputs = {"BTC": AssetDrawdownInput(symbol="BTC", max_drawdown=-0.5)}
    results = run_all_scenarios(allocations, drawdown_inputs, max_stress_scenario_drawdown=0.9)
    names = {r.scenario_name for r in results}
    assert names == {"HISTORICAL_WORST_DRAWDOWN", "ALTCOIN_CONTAGION_LUNA_FTX_STYLE"}


def test_empty_allocations_produce_zero_drawdown():
    result = historical_worst_drawdown_scenario({}, {}, max_stress_scenario_drawdown=0.5)
    assert result.portfolio_drawdown_pct == 0.0
    assert result.flagged is False
