import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.benchmarks.triple_barrier import evaluate_triple_barrier
from app.database.repository import DecisionOutcomeRepository, MarketSnapshotRepository

logger = logging.getLogger("crypto_ai_portfolio.benchmarks")

# How far around decision_timestamp to search for an entry-price snapshot —
# Phase 1's collection cadence isn't guaranteed to land exactly on the
# decision instant.
ENTRY_PRICE_SEARCH_WINDOW = timedelta(hours=2)


@dataclass
class EvaluationResult:
    evaluated: int = 0
    still_unresolved: int = 0
    skipped_no_entry_price: int = 0

    @property
    def summary(self) -> str:
        return (
            f"evaluated={self.evaluated} still_unresolved={self.still_unresolved} "
            f"skipped_no_entry_price={self.skipped_no_entry_price}"
        )


class OutcomeEvaluationService:
    """Task 4's evaluation step: for every UNRESOLVED `decision_outcomes`
    row, walks forward through actual subsequent `market_snapshots` and
    backfills `realized_return`/`outcome_label` using the triple-barrier
    scheme — manually triggerable (`--evaluate-outcomes`), not scheduled
    yet."""

    def __init__(
        self,
        decision_outcome_repo: DecisionOutcomeRepository,
        snapshot_repo: MarketSnapshotRepository,
    ) -> None:
        self._decision_outcome_repo = decision_outcome_repo
        self._snapshot_repo = snapshot_repo

    def run(self, now: datetime | None = None) -> EvaluationResult:
        now = now or datetime.now(UTC)
        result = EvaluationResult()

        # limit=None (2026-09-27 follow-up to the JudgeDecision pagination
        # work): every currently UNRESOLVED row is evaluated every run, not
        # just the first 500 -- this step is zero-cost/deterministic (no
        # LLM or external API call), so there's no reason to leave any of
        # a real backlog unprocessed. No FIFO/priority ordering is implied;
        # see DecisionOutcomeRepository.get_unresolved's own docstring.
        unresolved = self._decision_outcome_repo.get_unresolved(limit=None)
        for outcome in unresolved:
            horizon_end = outcome.decision_timestamp + timedelta(days=outcome.horizon_days)

            entry_snapshots = self._snapshot_repo.get_snapshots_in_range(
                outcome.asset_id,
                outcome.decision_timestamp - ENTRY_PRICE_SEARCH_WINDOW,
                outcome.decision_timestamp + ENTRY_PRICE_SEARCH_WINDOW,
            )
            if not entry_snapshots:
                result.skipped_no_entry_price += 1
                result.still_unresolved += 1
                continue
            entry_price = float(entry_snapshots[0].price)

            walk_end = min(now, horizon_end)
            series = self._snapshot_repo.get_snapshots_in_range(
                outcome.asset_id, outcome.decision_timestamp, walk_end
            )
            price_points = [(s.timestamp, float(s.price)) for s in series]

            label, realized_return, evaluated_at = evaluate_triple_barrier(
                entry_price, price_points, outcome.target_return, outcome.stop_return, horizon_end
            )
            if label == "UNRESOLVED":
                result.still_unresolved += 1
                continue

            self._decision_outcome_repo.update_outcome(
                outcome.decision_id, realized_return, label, evaluated_at
            )
            result.evaluated += 1
            logger.info(
                "Decision %s (asset %s): %s realized_return=%.4f",
                outcome.decision_id, outcome.asset_id, label, realized_return,
            )

        logger.info("Outcome evaluation complete: %s", result.summary)
        return result
