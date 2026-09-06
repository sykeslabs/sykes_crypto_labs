from datetime import UTC, datetime
from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.evidence_provenance import (
    DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE,
    MULTI_ENTRY_ASSET_SOURCES,
    group_observations_by_multi_entry_source,
    latest_value_as_of,
)
from app.database.models import AssetStatusHistory, SignalSource
from app.judge.decisions import DecisionValue
from app.llm.cost import COST_TRACKED_TABLES, CostGuard, CostLedgerRepository

# --- DecisionValue ---------------------------------------------------------

def test_decision_value_covers_expected_five_values():
    assert set(get_args(DecisionValue)) == {"BUY", "HOLD", "SELL", "WATCH", "NO_TRADE"}


# --- evidence provenance: latest_value_as_of --------------------------------

def _rows():
    return [
        {"retrieval_timestamp": datetime(2026, 1, 1, tzinfo=UTC), "value": "original"},
        {"retrieval_timestamp": datetime(2026, 1, 3, tzinfo=UTC), "value": "correction-1"},
        {"retrieval_timestamp": datetime(2026, 1, 5, tzinfo=UTC), "value": "correction-2"},
    ]


def test_latest_value_as_of_returns_most_recent_known_at_time():
    result = latest_value_as_of(_rows(), datetime(2026, 1, 4, tzinfo=UTC))
    assert result["value"] == "correction-1"


def test_latest_value_as_of_before_any_data_returns_none():
    assert latest_value_as_of(_rows(), datetime(2025, 12, 1, tzinfo=UTC)) is None


def test_latest_value_as_of_exact_boundary_is_inclusive():
    result = latest_value_as_of(_rows(), datetime(2026, 1, 3, tzinfo=UTC))
    assert result["value"] == "correction-1"


def test_latest_value_as_of_after_all_revisions_returns_newest():
    result = latest_value_as_of(_rows(), datetime(2026, 6, 1, tzinfo=UTC))
    assert result["value"] == "correction-2"


def test_decay_half_life_reference_has_known_source_types():
    assert DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["coingecko_price"] < DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["news"]
    assert DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["news"] < DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["macro"]


# --- group_observations_by_multi_entry_source (3g regression) ---------------
# Real bug found during 3g's point-in-time audit: naive dedup-by-source-name
# (setdefault(obs.source, ...)) silently kept only ONE of many dated-futures
# term-structure instruments sharing one source name, discarding the rest of
# the curve. These tests target that exact bug class directly.

class _FakeObs:
    def __init__(self, source, timeframe):
        self.source = source
        self.timeframe = timeframe


def test_group_observations_keeps_every_distinct_multi_entry_instrument():
    observations = [
        _FakeObs("deribit_futures_term_structure", "BTC-6SEP26"),
        _FakeObs("deribit_futures_term_structure", "BTC-25SEP26"),
        _FakeObs("deribit_futures_term_structure", "BTC-25DEC26"),
        _FakeObs("binance_funding_rate", None),  # single-value source, untouched
    ]
    single, multi = group_observations_by_multi_entry_source(observations)
    assert len(single) == 1
    assert single[0].source == "binance_funding_rate"
    assert len(multi["deribit_futures_term_structure"]) == 3
    assert {o.timeframe for o in multi["deribit_futures_term_structure"]} == {
        "BTC-6SEP26", "BTC-25SEP26", "BTC-25DEC26",
    }


def test_group_observations_dedupes_multi_entry_by_source_and_timeframe():
    # Two collection runs, each producing the same 2 instruments — newest
    # first (as get_latest_by_asset returns), duplicate (source, timeframe)
    # pairs across runs must collapse to one (the first/newest seen), not
    # accumulate duplicates.
    observations = [
        _FakeObs("deribit_futures_term_structure", "BTC-25SEP26"),  # run 2 (newest)
        _FakeObs("deribit_futures_term_structure", "BTC-25DEC26"),
        _FakeObs("deribit_futures_term_structure", "BTC-25SEP26"),  # run 1 (older duplicate)
        _FakeObs("deribit_futures_term_structure", "BTC-25DEC26"),
    ]
    _, multi = group_observations_by_multi_entry_source(observations)
    assert len(multi["deribit_futures_term_structure"]) == 2


def test_group_observations_single_value_sources_pass_through_unmodified():
    observations = [
        _FakeObs("binance_funding_rate", None),
        _FakeObs("volatility_risk_premium", None),
    ]
    single, multi = group_observations_by_multi_entry_source(observations)
    assert len(single) == 2
    assert multi == {}


def test_multi_entry_asset_sources_covers_both_venues():
    assert MULTI_ENTRY_ASSET_SOURCES == {
        "binance_futures_term_structure", "deribit_futures_term_structure",
    }


# --- AssetStatusHistory / SignalSource schemas ------------------------------

def test_asset_status_history_accepts_valid_status():
    entry = AssetStatusHistory(
        asset_id="a1", status="CANDIDATE", changed_at=datetime.now(UTC)
    )
    assert entry.status == "CANDIDATE"


def test_asset_status_history_rejects_invalid_status():
    with pytest.raises(ValidationError):
        AssetStatusHistory(asset_id="a1", status="ARCHIVED", changed_at=datetime.now(UTC))


def test_asset_status_history_to_row_serializes_datetime():
    entry = AssetStatusHistory(
        asset_id="a1", status="HELD", changed_at=datetime(2026, 1, 1, tzinfo=UTC), reason="test"
    )
    row = entry.to_row()
    assert row["asset_id"] == "a1"
    assert row["status"] == "HELD"
    assert isinstance(row["changed_at"], str)


def test_signal_source_accepts_valid_status():
    source = SignalSource(name="CoinGecko", enabled=True, status="OK")
    assert source.status == "OK"


def test_signal_source_rejects_invalid_status():
    with pytest.raises(ValidationError):
        SignalSource(name="X", enabled=True, status="BROKEN")


# --- CostLedgerRepository / COST_TRACKED_TABLES -----------------------------

class _FakeQueryResult:
    def __init__(self, data):
        self.data = data


class _FakeTableQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if r.get(column, "") >= value]
        return self

    def execute(self):
        return _FakeQueryResult(self._rows)


class FakeSupabaseClient:
    """Minimal fake mimicking supabase-py's `.table().select().gte().execute()`
    chain across arbitrary table names, for testing CostLedgerRepository's
    generic multi-table summing without a live database."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        return _FakeTableQuery(list(self._tables.get(name, [])))


def test_cost_tracked_tables_registers_llm_analyses():
    # Membership, not exact-equality: later sub-phases (3d's
    # model_market_assessments, 3e's judge_decisions, ...) legitimately add
    # more entries to this registry over time.
    assert COST_TRACKED_TABLES["llm_analyses"] == "timestamp"


def test_cost_ledger_sums_current_real_config():
    # COST_TRACKED_TABLES today is just {"llm_analyses": "timestamp"} — this
    # proves the generic path produces the same result Phase 2 relied on.
    client = FakeSupabaseClient({
        "llm_analyses": [
            {"timestamp": "2026-01-02T00:00:00+00:00", "estimated_cost": "0.05"},
            {"timestamp": "2026-01-03T00:00:00+00:00", "estimated_cost": "0.03"},
        ],
    })
    ledger = CostLedgerRepository(client)
    total = ledger.get_cost_sum_since(datetime(2026, 1, 1, tzinfo=UTC))
    assert total == Decimal("0.08")


def test_cost_ledger_sums_across_multiple_registered_tables(monkeypatch):
    monkeypatch.setattr(
        "app.llm.cost.COST_TRACKED_TABLES",
        {"llm_analyses": "timestamp", "judge_decisions": "created_at"},
    )
    client = FakeSupabaseClient({
        "llm_analyses": [{"timestamp": "2026-01-02T00:00:00+00:00", "estimated_cost": "1.5"}],
        "judge_decisions": [{"created_at": "2026-01-02T00:00:00+00:00", "estimated_cost": "2.5"}],
    })
    ledger = CostLedgerRepository(client)
    total = ledger.get_cost_sum_since(datetime(2026, 1, 1, tzinfo=UTC))
    assert total == Decimal("4.0")


def test_cost_ledger_ignores_rows_with_null_cost():
    client = FakeSupabaseClient({
        "llm_analyses": [
            {"timestamp": "2026-01-02T00:00:00+00:00", "estimated_cost": None},
            {"timestamp": "2026-01-02T00:00:00+00:00", "estimated_cost": "1.0"},
        ],
    })
    ledger = CostLedgerRepository(client)
    total = ledger.get_cost_sum_since(datetime(2026, 1, 1, tzinfo=UTC))
    assert total == Decimal("1.0")


def test_cost_guard_still_blocks_via_cost_ledger():
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("1"), max_monthly_llm_cost=Decimal("50"))
    client = FakeSupabaseClient({
        "llm_analyses": [{"timestamp": datetime.now(UTC).isoformat(), "estimated_cost": "1"}],
    })
    guard = CostGuard(settings, CostLedgerRepository(client))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Daily" in reason
