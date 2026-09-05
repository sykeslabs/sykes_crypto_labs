"""Portfolio Construction (task 3) — consumes Risk-Engine-adjusted sizing
and decides increase/hold/reduce/remove/initiate/hold-cash. Never forces
full capital deployment: HOLD_CASH is a real, expected outcome when nothing
clears the bar.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.config import Settings
from app.database.repository import PortfolioAllocationChangeRepository, PortfolioPositionRepository
from app.judge.schemas import JudgeDecisionRecord
from app.portfolio.schemas import PortfolioAllocationChange, PortfolioPosition
from app.risk.engine import SizedDecision

logger = logging.getLogger("crypto_ai_portfolio.portfolio")

PortfolioActionType = Literal["INITIATE", "INCREASE", "HOLD", "REDUCE", "REMOVE", "HOLD_CASH"]

# A tiny epsilon floor for risk_score in the risk_adjusted_alpha denominator
# — a decision with risk_score == 0 shouldn't produce an undefined/infinite
# ratio.
_RISK_SCORE_EPSILON = 0.05


@dataclass
class PortfolioAction:
    asset_id: str
    symbol: str
    action: PortfolioActionType
    previous_allocation: float
    new_allocation: float
    decision_id: str | None
    replaced_symbol: str | None = None
    blocked_no_capacity: bool = False


def risk_adjusted_alpha(expected_alpha: float, risk_score: float) -> float:
    return expected_alpha / max(risk_score, _RISK_SCORE_EPSILON)


class PortfolioConstructionService:
    def __init__(
        self,
        settings: Settings,
        position_repo: PortfolioPositionRepository,
        allocation_change_repo: PortfolioAllocationChangeRepository,
    ) -> None:
        self._settings = settings
        self._position_repo = position_repo
        self._allocation_change_repo = allocation_change_repo

    def apply(
        self,
        run_id: str,
        sized_decisions: list[SizedDecision],
        decisions_by_asset: dict[str, JudgeDecisionRecord],
        decision_ids_by_asset: dict[str, str],
    ) -> list[PortfolioAction]:
        self._apply_replacement_capacity_limit(sized_decisions, decisions_by_asset)

        actions = []
        now = datetime.now(UTC)
        for d in sized_decisions:
            action_type = self._classify(d)
            actions.append(PortfolioAction(
                asset_id=d.asset_id, symbol=d.symbol, action=action_type,
                previous_allocation=d.current_allocation, new_allocation=d.final_allocation,
                decision_id=decision_ids_by_asset.get(d.asset_id),
            ))

            if d.final_allocation != d.current_allocation:
                self._position_repo.upsert(PortfolioPosition(
                    asset_id=d.asset_id,
                    current_allocation=d.final_allocation,
                    last_decision_id=decision_ids_by_asset.get(d.asset_id),
                ))
                self._allocation_change_repo.insert(PortfolioAllocationChange(
                    asset_id=d.asset_id, run_id=run_id,
                    decision_id=decision_ids_by_asset.get(d.asset_id),
                    previous_allocation=d.current_allocation, new_allocation=d.final_allocation,
                    changed_at=now,
                ))

        logger.info(
            "Portfolio construction: %s",
            [(a.symbol, a.action, round(a.new_allocation, 4)) for a in actions],
        )
        return actions

    def _classify(self, d: SizedDecision) -> PortfolioActionType:
        if d.final_allocation == d.current_allocation:
            return "HOLD" if d.current_allocation > 0 else "HOLD_CASH"
        if d.current_allocation == 0 and d.final_allocation > 0:
            return "INITIATE"
        if d.final_allocation == 0:
            return "REMOVE"
        return "INCREASE" if d.final_allocation > d.current_allocation else "REDUCE"

    def _apply_replacement_capacity_limit(
        self, sized_decisions: list[SizedDecision], decisions_by_asset: dict[str, JudgeDecisionRecord]
    ) -> None:
        """Task 3's replacement rule: a brand-new candidate may only bump an
        existing holding out of the book when it clears
        MIN_REPLACEMENT_ALPHA_ADVANTAGE over that holding's own
        risk_adjusted_alpha, AND only when there's no room left under
        MAX_CONCURRENT_POSITIONS. Below capacity, new candidates are simply
        added — replacement is a capacity mechanism, not a quality filter
        applied unconditionally. Scoped to assets judged THIS run only (no
        fresh risk_adjusted_alpha exists for an idle holding outside today's
        candidate set)."""
        s = self._settings

        def alpha_of(d: SizedDecision) -> float:
            record = decisions_by_asset[d.asset_id]
            return risk_adjusted_alpha(record.expected_alpha, record.risk_score)

        would_be_held = [d for d in sized_decisions if d.final_allocation > 0]
        overflow = len(would_be_held) - s.max_concurrent_positions
        if overflow <= 0:
            return

        new_candidates = sorted(
            (d for d in sized_decisions if d.current_allocation == 0 and d.final_allocation > 0),
            key=alpha_of, reverse=True,
        )
        existing_held = sorted(
            (d for d in sized_decisions if d.current_allocation > 0 and d.final_allocation > 0),
            key=alpha_of,
        )

        while overflow > 0 and new_candidates:
            newest = new_candidates.pop(0)
            weakest = existing_held[0] if existing_held else None

            if weakest is not None and alpha_of(newest) > alpha_of(weakest) + s.min_replacement_alpha_advantage:
                weakest_alpha = alpha_of(weakest)
                weakest.final_allocation = 0.0
                existing_held.pop(0)
                overflow -= 1
                logger.info(
                    "%s replaces %s (risk_adjusted_alpha %.3f > %.3f + %.3f)",
                    newest.symbol, weakest.symbol, alpha_of(newest),
                    weakest_alpha, s.min_replacement_alpha_advantage,
                )
            else:
                newest.final_allocation = 0.0
                overflow -= 1
                logger.info(
                    "%s blocked: no capacity and no existing holding clears "
                    "MIN_REPLACEMENT_ALPHA_ADVANTAGE (%.3f)",
                    newest.symbol, s.min_replacement_alpha_advantage,
                )
