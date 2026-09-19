from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.judge.schemas import JudgeDecisionRecord
from app.portfolio.construction import PortfolioConstructionService, risk_adjusted_alpha
from app.portfolio.schemas import PortfolioAllocationChange
from app.risk.engine import SizedDecision


def _sized(asset_id, symbol, current, final, is_new=False, previous_system_target=None, decision="BUY"):
    # previous_system_target defaults to `current` (no manual/external
    # drift) -- _classify/_apply_replacement_capacity_limit are judged
    # against the strategy's own previous target, not real holdings (see
    # RiskEngine._strategy_turnover_delta's docstring for why), so tests
    # that aren't specifically about a drift scenario keep the two equal.
    if previous_system_target is None:
        previous_system_target = current
    return SizedDecision(
        asset_id=asset_id, symbol=symbol, decision=decision, original_decision=decision,
        confidence=0.7, current_allocation=current, previous_system_target=previous_system_target,
        final_allocation=final, vol_scalar=1.0, agreement_scalar=1.0, is_new_position=is_new,
    )


def _decision_record(asset_id, expected_alpha=0.05, risk_score=0.4):
    return JudgeDecisionRecord(
        run_id="RUN-1", asset_id=asset_id, created_at=datetime.now(UTC), decision="BUY",
        confidence=0.7, target_allocation=0.10, expected_return=0.1, expected_alpha=expected_alpha,
        risk_score=risk_score, uncertainty=0.3, model_agreement=0.9, source_agreement=0.9,
        investment_horizon_days=30, key_evidence=[], contradictory_evidence=[], key_risks=[],
        invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity="n/a", regime_id="r1",
        prompt_template_id="p1", estimated_cost=Decimal("0.01"),
    )


class FakePositionRepo:
    def __init__(self):
        self.upserted = []
        self._by_asset = {}

    def upsert(self, position):
        self.upserted.append(position)
        self._by_asset[position.asset_id] = position

    def get_all(self):
        return dict(self._by_asset)


class FakeAllocationChangeRepo:
    def __init__(self):
        self.inserted = []

    def insert(self, change):
        self.inserted.append(change)


def _service(**settings_overrides):
    settings = Settings(_env_file=None, **settings_overrides)
    return PortfolioConstructionService(settings, FakePositionRepo(), FakeAllocationChangeRepo())


def test_risk_adjusted_alpha_basic():
    assert risk_adjusted_alpha(0.10, 0.5) == 0.20


def test_risk_adjusted_alpha_floors_risk_score_denominator():
    # risk_score=0 shouldn't blow up to infinity.
    assert risk_adjusted_alpha(0.10, 0.0) == 0.10 / 0.05


def test_classify_initiate_increase_hold_reduce_remove_hold_cash():
    service = _service(max_concurrent_positions=99)
    decisions = [
        _sized("a1", "INITIATE", 0.0, 0.05, is_new=True),
        _sized("a2", "INCREASE", 0.05, 0.10),
        _sized("a3", "HOLD", 0.05, 0.05),
        _sized("a4", "REDUCE", 0.10, 0.05),
        _sized("a5", "REMOVE", 0.05, 0.0),
        _sized("a6", "HOLDCASH", 0.0, 0.0),
    ]
    by_asset = {d.asset_id: _decision_record(d.asset_id) for d in decisions}
    ids = {d.asset_id: f"dec-{d.asset_id}" for d in decisions}

    actions = service.apply("RUN-1", decisions, by_asset, ids)
    action_map = {a.symbol: a.action for a in actions}

    assert action_map == {
        "INITIATE": "INITIATE",
        "INCREASE": "INCREASE",
        "HOLD": "HOLD",
        "REDUCE": "REDUCE",
        "REMOVE": "REMOVE",
        "HOLDCASH": "HOLD_CASH",
    }


def test_apply_persists_position_and_logs_change_only_when_allocation_changes():
    position_repo = FakePositionRepo()
    change_repo = FakeAllocationChangeRepo()
    settings = Settings(_env_file=None, max_concurrent_positions=99)
    service = PortfolioConstructionService(settings, position_repo, change_repo)

    decisions = [_sized("a1", "BTC", 0.0, 0.05, is_new=True), _sized("a2", "ETH", 0.05, 0.05)]
    by_asset = {d.asset_id: _decision_record(d.asset_id) for d in decisions}
    ids = {d.asset_id: f"dec-{d.asset_id}" for d in decisions}

    service.apply("RUN-1", decisions, by_asset, ids)

    assert len(position_repo.upserted) == 1  # only the changed one (BTC)
    assert len(change_repo.inserted) == 1
    assert position_repo.upserted[0].asset_id == "a1"


# --- change_reason classification (2026-09-17 turnover-accounting fix) --------
#
# Real bug: WATCH/NO_TRADE risk-control corrections (RiskEngine.size_one's
# min(current_allocation, max_single_asset_allocation) clamp) were persisted
# indistinguishably from real strategy decisions, so get_turnover_since
# silently re-counted them as strategy turnover even though
# _strategy_turnover_delta already exempts them at decision time. Fixed by
# classifying from d.decision (the already-gated SizedDecision value) at
# persistence time -- see migrations/0021.

def test_watch_decision_that_changes_allocation_persists_risk_control():
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "BTC", current=0.30, final=0.15, previous_system_target=0.30, decision="WATCH")
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "risk_control"


def test_no_trade_decision_that_changes_allocation_persists_risk_control():
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "JASMY", current=0.0002, final=0.0, previous_system_target=0.0002, decision="NO_TRADE")
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "risk_control"


@pytest.mark.parametrize("decision", ["BUY", "SELL"])
def test_buy_sell_decisions_that_change_allocation_persist_strategy(decision):
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "SOL", current=0.10, final=0.20, previous_system_target=0.10, decision=decision)
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "strategy"


def test_capped_buy_that_reduces_allocation_still_persists_strategy_not_risk_control():
    # A real sizing decision (decision stays "BUY") whose final_allocation is
    # LOWER than previous_system_target -- e.g. a rebalance-down driven by a
    # confidence/vol scalar, not a WATCH/NO_TRADE risk-control clamp.
    # Classification must follow d.decision, never the derived REDUCE/
    # INCREASE PortfolioActionType from _classify.
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "BTC", current=0.30, final=0.20, previous_system_target=0.30, decision="BUY")
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "strategy"


def test_confidence_gated_buy_downgraded_to_watch_persists_risk_control_not_strategy():
    # Reproduces the real 2026-09-17 NEAR row: judge_decisions.decision was
    # raw "BUY" (confidence 0.50, below MIN_BUY_CONFIDENCE=0.55), but
    # _apply_confidence_gate downgraded it to WATCH before sizing.
    # SizedDecision.decision holds the POST-gate value; original_decision
    # keeps the raw value for audit only. Classification must use .decision.
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = SizedDecision(
        asset_id="a1", symbol="NEAR", decision="WATCH", original_decision="BUY",
        confidence=0.50, current_allocation=0.0, previous_system_target=0.0,
        final_allocation=0.05, vol_scalar=1.0, agreement_scalar=1.0, is_new_position=False,
    )
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "risk_control"


# --- A2 cap-compliance correction (2026-09-17) --------------------------------

def test_a2_oversized_target_reduced_to_cap_via_hold_persists_risk_control():
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "BTC", current=0.333, final=0.15, previous_system_target=0.30, decision="HOLD")
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "risk_control"


def test_a2_sell_to_zero_from_oversized_target_persists_risk_control():
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "BTC", current=0.333, final=0.0, previous_system_target=0.30, decision="SELL")
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].change_reason == "risk_control"


@pytest.mark.parametrize("decision,current,previous,final", [
    ("HOLD", 0.10, 0.10, 0.12),      # ordinary, not oversized -> strategy
    ("HOLD", 0.333, 0.30, 0.15),     # A2: reduced to exactly cap -> risk_control
    ("HOLD", 0.333, 0.30, 0.10),     # A2: reduced below cap -> risk_control
    ("SELL", 0.333, 0.30, 0.0),      # A2: sell-to-zero from oversized -> risk_control
    ("HOLD", 0.333, 0.30, 0.20),     # still above cap -> strategy (A2 must not fire)
    ("HOLD", 0.15, 0.15, 0.10),      # previous exactly at cap, not oversized -> strategy
    ("WATCH", 0.333, 0.30, 0.15),    # A1, unaffected by A2 -> risk_control
])
def test_risk_engine_and_construction_predicates_agree_on_classification(decision, current, previous, final):
    # Guards against the Risk Engine's turnover exemption and Portfolio
    # Construction's change_reason classification silently drifting apart
    # into two subtly different A2 predicates -- both must use the exact
    # same is_cap_compliance_correction function.
    settings = Settings(_env_file=None, max_concurrent_positions=99)
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(settings, FakePositionRepo(), change_repo)
    d = _sized("a1", "X", current=current, final=final, previous_system_target=previous, decision=decision)

    from app.risk.engine import RiskEngine
    engine = RiskEngine(settings)
    exempt_from_turnover = engine._strategy_turnover_delta(d) == 0.0

    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})
    if change_repo.inserted:
        persisted_as_risk_control = change_repo.inserted[0].change_reason == "risk_control"
        assert persisted_as_risk_control == exempt_from_turnover


def test_watch_no_op_persists_no_row_at_all_regardless_of_change_reason():
    change_repo = FakeAllocationChangeRepo()
    service = PortfolioConstructionService(
        Settings(_env_file=None, max_concurrent_positions=99), FakePositionRepo(), change_repo,
    )
    d = _sized("a1", "BTC", current=0.10, final=0.10, previous_system_target=0.10, decision="WATCH")
    service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert change_repo.inserted == []


# --- PortfolioAllocationChange schema (change_reason field) -------------------

def test_portfolio_allocation_change_reason_defaults_to_strategy():
    change = PortfolioAllocationChange(
        asset_id="a1", run_id="RUN-1", decision_id="d1",
        previous_allocation=0.0, new_allocation=0.05, changed_at=datetime.now(UTC),
    )
    assert change.change_reason == "strategy"


def test_portfolio_allocation_change_to_row_includes_change_reason():
    change = PortfolioAllocationChange(
        asset_id="a1", run_id="RUN-1", decision_id="d1",
        previous_allocation=0.0, new_allocation=0.05, changed_at=datetime.now(UTC),
        change_reason="risk_control",
    )
    assert change.to_row()["change_reason"] == "risk_control"


def test_portfolio_allocation_change_rejects_invalid_change_reason():
    with pytest.raises(ValidationError):
        PortfolioAllocationChange(
            asset_id="a1", run_id="RUN-1", decision_id="d1",
            previous_allocation=0.0, new_allocation=0.05, changed_at=datetime.now(UTC),
            change_reason="not_a_real_reason",
        )


def test_replacement_swaps_weak_holding_for_stronger_new_candidate_over_capacity():
    service = _service(max_concurrent_positions=1, min_replacement_alpha_advantage=0.01)
    existing_weak = _sized("weak", "WEAK", current=0.05, final=0.05)  # held, low alpha
    new_strong = _sized("strong", "STRONG", current=0.0, final=0.05, is_new=True)  # new, high alpha

    by_asset = {
        "weak": _decision_record("weak", expected_alpha=0.01, risk_score=0.5),   # alpha=0.02
        "strong": _decision_record("strong", expected_alpha=0.20, risk_score=0.5),  # alpha=0.40
    }
    ids = {"weak": "dec-weak", "strong": "dec-strong"}

    actions = service.apply("RUN-1", [existing_weak, new_strong], by_asset, ids)
    action_by_symbol = {a.symbol: a for a in actions}

    assert action_by_symbol["WEAK"].action == "REMOVE"
    assert action_by_symbol["STRONG"].action == "INITIATE"


def test_replacement_blocked_when_advantage_insufficient():
    service = _service(max_concurrent_positions=1, min_replacement_alpha_advantage=0.50)
    existing = _sized("held", "HELD", current=0.05, final=0.05)
    new_candidate = _sized("new", "NEW", current=0.0, final=0.05, is_new=True)

    by_asset = {
        "held": _decision_record("held", expected_alpha=0.05, risk_score=0.5),
        "new": _decision_record("new", expected_alpha=0.06, risk_score=0.5),  # not enough advantage
    }
    ids = {"held": "dec-held", "new": "dec-new"}

    actions = service.apply("RUN-1", [existing, new_candidate], by_asset, ids)
    action_by_symbol = {a.symbol: a for a in actions}

    assert action_by_symbol["HELD"].action == "HOLD"
    assert action_by_symbol["NEW"].action == "HOLD_CASH"  # blocked: stays at 0 allocation


def test_apply_records_previous_system_target_and_real_holdings_separately():
    # Real bug fixed 2026-09-14: previous_allocation used to be real
    # holdings; it must now be the strategy's own previous target, with
    # real holdings kept alongside (actual_allocation_before) for audit
    # only. Reproduces the exact shape of the real incident: real holdings
    # (0.30) far exceed the strategy's own previous target (0.10).
    position_repo = FakePositionRepo()
    change_repo = FakeAllocationChangeRepo()
    settings = Settings(_env_file=None, max_concurrent_positions=99)
    service = PortfolioConstructionService(settings, position_repo, change_repo)

    d = _sized("a1", "BTC", current=0.30, final=0.12, previous_system_target=0.10)
    by_asset = {"a1": _decision_record("a1")}
    ids = {"a1": "dec-a1"}

    service.apply("RUN-1", [d], by_asset, ids)

    assert len(change_repo.inserted) == 1
    change = change_repo.inserted[0]
    assert change.previous_allocation == pytest.approx(0.10)  # strategy's own previous target
    assert change.new_allocation == pytest.approx(0.12)
    assert change.actual_allocation_before == pytest.approx(0.30)  # real holdings, audit only
    assert change.baseline_semantics == "system_target"
    assert position_repo.upserted[0].current_allocation == pytest.approx(0.12)


def test_apply_no_write_when_strategy_target_unchanged_despite_real_holdings_drift():
    # If the strategy's OWN target doesn't change, nothing should be
    # persisted -- even if real holdings differ wildly from both.
    position_repo = FakePositionRepo()
    change_repo = FakeAllocationChangeRepo()
    settings = Settings(_env_file=None, max_concurrent_positions=99)
    service = PortfolioConstructionService(settings, position_repo, change_repo)

    d = _sized("a1", "BTC", current=0.30, final=0.10, previous_system_target=0.10)  # final == previous target
    by_asset = {"a1": _decision_record("a1")}
    ids = {"a1": "dec-a1"}

    service.apply("RUN-1", [d], by_asset, ids)

    assert change_repo.inserted == []
    assert position_repo.upserted == []


def test_remove_action_carries_actual_allocation_before_when_a_real_position_existed():
    # REMOVE fires (previous_system_target > 0 -> final_allocation == 0);
    # real holdings were genuinely nonzero -- a real position is being
    # closed, not just bookkeeping.
    service = _service(max_concurrent_positions=99)
    d = _sized("a1", "BTC", current=0.20, final=0.0, previous_system_target=0.10)
    actions = service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert actions[0].action == "REMOVE"
    assert actions[0].actual_allocation_before == pytest.approx(0.20)


def test_remove_action_carries_zero_actual_allocation_when_nothing_was_really_held():
    # Reproduces the real 2026-09-16 run's BNB/HYPE case: the STRATEGY's own
    # stale target snaps to zero (REMOVE, per _classify's turnover-
    # accounting purpose), but real holdings were already 0.0 -- nothing is
    # actually being sold. `actual_allocation_before` must make this
    # distinguishable without a separate holdings_ledger join.
    service = _service(max_concurrent_positions=99)
    d = _sized("a1", "BNB", current=0.0, final=0.0, previous_system_target=0.00757)
    actions = service.apply("RUN-1", [d], {"a1": _decision_record("a1")}, {"a1": "dec-a1"})

    assert actions[0].action == "REMOVE"
    assert actions[0].actual_allocation_before == pytest.approx(0.0)


def test_no_replacement_needed_under_capacity():
    service = _service(max_concurrent_positions=10)
    a = _sized("a1", "BTC", 0.0, 0.05, is_new=True)
    b = _sized("a2", "ETH", 0.0, 0.05, is_new=True)
    by_asset = {"a1": _decision_record("a1"), "a2": _decision_record("a2")}
    ids = {"a1": "d1", "a2": "d2"}

    actions = service.apply("RUN-1", [a, b], by_asset, ids)
    assert {a.action for a in actions} == {"INITIATE"}


def test_replacement_capacity_judged_against_strategy_target_not_real_holdings():
    # A real, substantial manually-held position (0.40!) that the strategy
    # has never targeted must be bucketed as a "new candidate" competing
    # for capacity, NOT as a protected "existing_held" position just
    # because you personally already own a lot of it. `genuinely_targeted`
    # (previous_system_target > 0) is the only member of the real
    # existing_held bucket, and gets correctly replaced by a stronger new
    # candidate -- real holdings size plays no role in this decision.
    service = _service(max_concurrent_positions=2, min_replacement_alpha_advantage=0.01)
    manually_held_never_targeted = _sized(
        "manual", "MANUAL", current=0.40, final=0.40, previous_system_target=0.0,
    )
    genuinely_targeted = _sized("held", "HELD", current=0.0, final=0.05, previous_system_target=0.05)
    new_strong_candidate = _sized("strong", "STRONG", current=0.0, final=0.05, is_new=True)

    by_asset = {
        "manual": _decision_record("manual", expected_alpha=0.01, risk_score=0.5),
        "held": _decision_record("held", expected_alpha=0.02, risk_score=0.5),
        "strong": _decision_record("strong", expected_alpha=0.20, risk_score=0.5),
    }
    ids = {"manual": "dec-manual", "held": "dec-held", "strong": "dec-strong"}

    actions = service.apply(
        "RUN-1", [manually_held_never_targeted, genuinely_targeted, new_strong_candidate], by_asset, ids,
    )
    action_by_symbol = {a.symbol: a for a in actions}

    # STRONG (a genuine new candidate) replaces HELD (the only real
    # existing_held member, previous_system_target > 0) -- MANUAL, despite
    # real holdings of 0.40, is a "new candidate" from the strategy's own
    # point of view and is correctly treated as opening a fresh position,
    # not as an already-held one immune to replacement.
    assert action_by_symbol["STRONG"].action == "INITIATE"
    assert action_by_symbol["HELD"].action == "REMOVE"
    assert action_by_symbol["MANUAL"].action == "INITIATE"  # previous_system_target 0 -> 0.40


# --- End-to-end, multi-run regression: no repeated double-charging ------------
#
# The single most important property of the 2026-09-14 fix, per its own
# audit: an UNRESOLVED gap between real holdings and the strategy's own
# target must be observable repeatedly (real risk gating keeps seeing the
# truth every run) WITHOUT being repeatedly charged as new strategy
# turnover each time the Judge revisits that asset. These tests run the
# REAL PortfolioConstructionService.apply() across multiple simulated runs,
# feeding each run's own persisted portfolio_positions state forward into
# the next (exactly as app/main.py does via a fresh
# `portfolio_position_repo.get_all()` call each run), never resetting
# state by hand between runs.

def test_persistent_external_gap_is_not_repeatedly_charged_across_multiple_runs():
    # System target = 10% BTC. Real holdings = 30% (a persistent, never-
    # resolving manual-trade gap). The Judge keeps recommending exactly the
    # same 10% target every run (it never changes its mind). Replayed 4
    # times: the real external 20pp gap must be visible every time (via
    # `actual_allocation_before`) but NEVER counted as strategy turnover,
    # and NO write should occur after the very first run (nothing about
    # the strategy's own target ever changes).
    position_repo = FakePositionRepo()
    change_repo = FakeAllocationChangeRepo()
    settings = Settings(_env_file=None, max_concurrent_positions=99)
    service = PortfolioConstructionService(settings, position_repo, change_repo)

    REAL_HOLDINGS = 0.30  # persistent, never resolves
    STRATEGY_TARGET = 0.10  # the Judge's own recommendation, unchanged every run

    for run_number in range(1, 5):
        previous_system_target = position_repo.get_all().get("a1")
        previous_system_target = previous_system_target.current_allocation if previous_system_target else 0.0
        d = _sized(
            "a1", "BTC", current=REAL_HOLDINGS, final=STRATEGY_TARGET,
            previous_system_target=previous_system_target,
        )
        by_asset = {"a1": _decision_record("a1")}
        ids = {"a1": f"dec-run{run_number}"}
        service.apply(f"RUN-{run_number}", [d], by_asset, ids)

    # Exactly ONE real strategy-turnover event across all 4 runs (the
    # initial 0.0 -> 0.10 bootstrap on run 1) -- runs 2-4 are genuine no-ops
    # on the strategy's own bookkeeping, despite the persistent real gap.
    assert len(change_repo.inserted) == 1
    assert change_repo.inserted[0].previous_allocation == pytest.approx(0.0)
    assert change_repo.inserted[0].new_allocation == pytest.approx(0.10)
    assert change_repo.inserted[0].actual_allocation_before == pytest.approx(0.30)
    # Total counted strategy turnover across all 4 runs = 10pp, NOT 4x20pp
    # (the real external gap) or 4x10pp (double-counting the bootstrap).
    total_counted_turnover = sum(
        abs(c.new_allocation - c.previous_allocation) for c in change_repo.inserted
    )
    assert total_counted_turnover == pytest.approx(0.10)


def test_genuine_strategy_churn_is_counted_independently_across_runs():
    # 10% -> 20% -> 15% -> 25%: the strategy genuinely changes its mind 3
    # times in a row (real holdings stay irrelevant/matching throughout --
    # no manual drift in this scenario). Each real strategy move must be
    # counted independently; total turnover = 10 + 5 + 10 = 25pp, not
    # netted to the 15pp difference between the first and last target.
    position_repo = FakePositionRepo()
    change_repo = FakeAllocationChangeRepo()
    settings = Settings(_env_file=None, max_concurrent_positions=99)
    service = PortfolioConstructionService(settings, position_repo, change_repo)

    targets = [0.10, 0.20, 0.15, 0.25]
    # Seed the initial 10% target (run 0, bootstrap) before the 3 genuine
    # churn steps under test.
    seed = _sized("a1", "BTC", current=targets[0], final=targets[0], previous_system_target=0.0)
    service.apply("RUN-0", [seed], {"a1": _decision_record("a1")}, {"a1": "dec-0"})
    change_repo.inserted.clear()  # only count the 3 genuine churn steps below

    for i in range(1, len(targets)):
        previous_system_target = position_repo.get_all()["a1"].current_allocation
        d = _sized(
            "a1", "BTC", current=targets[i], final=targets[i],
            previous_system_target=previous_system_target,
        )
        service.apply(f"RUN-{i}", [d], {"a1": _decision_record("a1")}, {"a1": f"dec-{i}"})

    assert len(change_repo.inserted) == 3
    deltas = [abs(c.new_allocation - c.previous_allocation) for c in change_repo.inserted]
    assert deltas == pytest.approx([0.10, 0.05, 0.10])  # 10->20, 20->15, 15->25
    assert sum(deltas) == pytest.approx(0.25)  # NOT netted to |0.25 - 0.10| = 0.15
