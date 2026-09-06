from datetime import UTC, datetime
from decimal import Decimal

from app.config.settings import Settings
from app.judge.schemas import JudgeDecisionRecord
from app.portfolio.construction import PortfolioConstructionService, risk_adjusted_alpha
from app.risk.engine import SizedDecision


def _sized(asset_id, symbol, current, final, is_new=False):
    return SizedDecision(
        asset_id=asset_id, symbol=symbol, decision="BUY", original_decision="BUY",
        confidence=0.7, current_allocation=current, final_allocation=final,
        vol_scalar=1.0, agreement_scalar=1.0, is_new_position=is_new,
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

    def upsert(self, position):
        self.upserted.append(position)


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


def test_no_replacement_needed_under_capacity():
    service = _service(max_concurrent_positions=10)
    a = _sized("a1", "BTC", 0.0, 0.05, is_new=True)
    b = _sized("a2", "ETH", 0.0, 0.05, is_new=True)
    by_asset = {"a1": _decision_record("a1"), "a2": _decision_record("a2")}
    ids = {"a1": "d1", "a2": "d2"}

    actions = service.apply("RUN-1", [a, b], by_asset, ids)
    assert {a.action for a in actions} == {"INITIATE"}
