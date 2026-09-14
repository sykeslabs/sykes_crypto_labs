"""In-memory adapter repos used only by 3e.1's replay (`app/benchmarks/replay.py`).

None of these ever touch the live database — they satisfy the exact same
duck-typed interfaces `build_assessment_context`/`build_judge_context`/
`RiskEngine`/`PortfolioConstructionService` already depend on (the same
pattern the test suite uses), so those real, already-shipped, live-verified
classes run completely unmodified against reconstructed historical data.

This isolation is a safety requirement, not just a convenience: Portfolio
Construction writes position/allocation-change rows, and those must never
land in the live `portfolio_positions`/`portfolio_allocation_changes` tables
— a backfill run must never corrupt real paper-trading state.
"""

from datetime import datetime

from app.portfolio.schemas import PortfolioAllocationChange, PortfolioPosition


class StaticRegimeRepo:
    def __init__(self, regime):
        self._regime = regime

    def get_latest(self):
        return self._regime


class StaticEvidenceRepo:
    def __init__(self, evidence_by_asset: dict):
        self._evidence_by_asset = evidence_by_asset

    def get_latest_by_asset(self, asset_id):
        return self._evidence_by_asset.get(asset_id, [])


class StaticSnapshotRepo:
    """`snapshots_by_asset` values are newest-first, matching the real
    `MarketSnapshotRepository`'s contract."""

    def __init__(self, snapshots_by_asset: dict):
        self._snapshots_by_asset = snapshots_by_asset

    def get_latest_snapshot(self, asset_id):
        rows = self._snapshots_by_asset.get(asset_id, [])
        return rows[0] if rows else None

    def get_recent_snapshots(self, asset_id, limit=10):
        return self._snapshots_by_asset.get(asset_id, [])[:limit]


class StaticAssessmentRepo:
    def __init__(self, assessments: list):
        self._assessments = assessments

    def get_latest_run_assessments(self):
        return self._assessments


class StaticAdversarialRepo:
    """In-memory adversarial-research (3f) lookup, scoped to exactly one
    replayed day's own freshly-computed records -- avoids the real
    `AdversarialResearchRepository.get_latest_by_asset`'s "most recent by
    real insertion time, across every run" semantics, which would be
    ambiguous/unsafe to rely on directly while a backfill run is actively
    inserting new rows for many simulated days in a single real-time
    session."""

    def __init__(self, records_by_asset_id: dict):
        self._records_by_asset_id = records_by_asset_id

    def get_latest_by_asset(self, asset_id):
        return self._records_by_asset_id.get(asset_id)


class AsOfLLMAnalysisRepo:
    """Wraps the real repo's point-in-time method behind the same method
    name/signature `build_judge_context` calls on a live repo, so the
    interface is identical — just historically safe underneath."""

    def __init__(self, real_repo, as_of: datetime):
        self._real_repo = real_repo
        self._as_of = as_of

    def get_latest_by_asset(self, asset_id, limit=3):
        return self._real_repo.get_latest_by_asset_as_of(asset_id, self._as_of, limit)


class AsOfAssetStatusRepo:
    def __init__(self, real_repo, as_of: datetime):
        self._real_repo = real_repo
        self._as_of = as_of

    def get_latest_status(self, asset_id):
        return self._real_repo.get_latest_status_as_of(asset_id, self._as_of)


class InMemoryPortfolioPositionRepo:
    """Isolated, in-memory-only simulated portfolio state for one replay
    run — never the live `portfolio_positions` table."""

    def __init__(self):
        self._positions: dict[str, PortfolioPosition] = {}

    def get_all(self) -> dict[str, PortfolioPosition]:
        return dict(self._positions)

    def upsert(self, position: PortfolioPosition) -> None:
        self._positions[position.asset_id] = position


class InMemoryAllocationChangeRepo:
    """Isolated, in-memory-only simulated allocation-change log for one
    replay run — never the live `portfolio_allocation_changes` table."""

    def __init__(self):
        self._changes: list[PortfolioAllocationChange] = []

    def insert(self, change: PortfolioAllocationChange) -> None:
        self._changes.append(change)

    def get_turnover_since(self, since: datetime) -> float:
        return sum(
            abs(c.new_allocation - c.previous_allocation)
            for c in self._changes
            if c.changed_at >= since
        )
