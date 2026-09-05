"""Deterministic Risk Engine (task 2) — hard-gates and re-sizes the Judge's
*unconstrained* output. Nothing here is AI-influenced; every formula is
simple and inspectable by design (this is a paper system, not a production
risk desk), per PHASE3E_PROMPT.md's own instruction.
"""

from dataclasses import dataclass

from app.config import Settings
from app.judge.decisions import DecisionValue
from app.judge.schemas import JudgeDecisionRecord
from app.risk.correlation import compute_correlation_matrix, flag_concentrated_pairs

# Never let agreement scale a position to zero outright — a floor keeps a
# weak-agreement BUY a (small) real position rather than indistinguishable
# from a hard confidence-gate downgrade.
AGREEMENT_SCALAR_FLOOR = 0.3


@dataclass
class SizedDecision:
    asset_id: str
    symbol: str
    decision: DecisionValue
    original_decision: DecisionValue
    confidence: float
    current_allocation: float
    final_allocation: float
    vol_scalar: float
    agreement_scalar: float
    is_new_position: bool
    correlation_flagged: bool = False
    correlation_reason: str | None = None
    turnover_capped: bool = False


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def size_one(
        self,
        decision: JudgeDecisionRecord,
        symbol: str,
        volatility_30d: float | None,
        current_allocation: float,
    ) -> SizedDecision:
        s = self._settings
        gated_decision = self._apply_confidence_gate(decision.decision, decision.confidence, current_allocation)
        is_new_position = current_allocation == 0 and gated_decision == "BUY"

        if gated_decision == "SELL":
            final_allocation, vol_scalar, agreement_scalar = 0.0, 1.0, 1.0
        elif gated_decision in ("WATCH", "NO_TRADE"):
            # No change to current exposure — these are not sizing decisions.
            final_allocation, vol_scalar, agreement_scalar = current_allocation, 1.0, 1.0
        else:  # BUY or HOLD-with-a-resize
            vol_scalar = self._volatility_scalar(volatility_30d)
            agreement_scalar = self._agreement_scalar(decision.model_agreement, decision.source_agreement)
            raw_allocation = decision.target_allocation * vol_scalar * agreement_scalar
            capped = min(raw_allocation, s.max_single_asset_allocation)
            if is_new_position:
                capped = min(capped, s.max_new_position_size)
            final_allocation = capped

        return SizedDecision(
            asset_id=decision.asset_id,
            symbol=symbol,
            decision=gated_decision,
            original_decision=decision.decision,
            confidence=decision.confidence,
            current_allocation=current_allocation,
            final_allocation=final_allocation,
            vol_scalar=vol_scalar,
            agreement_scalar=agreement_scalar,
            is_new_position=is_new_position,
        )

    def _apply_confidence_gate(
        self, decision: DecisionValue, confidence: float, current_allocation: float
    ) -> DecisionValue:
        s = self._settings
        if decision == "BUY" and confidence < s.min_buy_confidence:
            return "WATCH"
        if decision == "SELL" and confidence < s.min_sell_confidence:
            return "HOLD"
        if decision in ("BUY", "SELL") and current_allocation > 0 and confidence < s.min_rebalance_confidence:
            # Resizing an existing position needs the (generally lower)
            # rebalance-confidence bar too, not just the open/close bars.
            return "HOLD"
        return decision

    def _volatility_scalar(self, volatility_30d: float | None) -> float:
        """Inverse-volatility scaling: an asset at exactly
        RISK_TARGET_VOLATILITY gets no adjustment; more volatile assets
        scale down. Capped at 1.0 — this reduces risk, it never levers up a
        low-volatility asset above the Judge's own target_allocation."""
        if not volatility_30d or volatility_30d <= 0:
            return 1.0  # unknown volatility -> no adjustment, never silently zeroed
        return min(1.0, self._settings.risk_target_volatility / volatility_30d)

    def _agreement_scalar(self, model_agreement: float, source_agreement: float) -> float:
        """Scales position size down further when 3d's model_agreement and
        the Judge's own source_agreement are both weak — composed with (not
        replacing) the volatility scalar above."""
        combined = (model_agreement + source_agreement) / 2
        return max(AGREEMENT_SCALAR_FLOOR, combined)

    def flag_correlations(
        self, sized_decisions: list[SizedDecision], returns_by_symbol: dict[str, list[float]]
    ) -> None:
        """Mutates `sized_decisions` in place: flags (never blocks) pairs of
        assets both being increased/opened whose 30d daily-return
        correlation is at/above `correlation_flag_threshold`."""
        increasing = {
            d.symbol: d
            for d in sized_decisions
            if d.final_allocation > d.current_allocation
        }
        matrix = compute_correlation_matrix(
            {s: r for s, r in returns_by_symbol.items() if s in increasing}
        )
        flagged_pairs = flag_concentrated_pairs(matrix, self._settings.correlation_flag_threshold)
        for symbol_a, symbol_b, corr in flagged_pairs:
            reason = f"Correlated with {symbol_b} at {corr:.2f} (both being increased)"
            increasing[symbol_a].correlation_flagged = True
            increasing[symbol_a].correlation_reason = reason
            reason_b = f"Correlated with {symbol_a} at {corr:.2f} (both being increased)"
            increasing[symbol_b].correlation_flagged = True
            increasing[symbol_b].correlation_reason = reason_b

    def apply_turnover_cap(
        self, sized_decisions: list[SizedDecision], turnover_used_this_week: float
    ) -> None:
        """Mutates `sized_decisions` in place: if this run's total proposed
        turnover would push the trailing-week total over
        MAX_WEEKLY_TURNOVER, scales every proposed CHANGE down by the same
        proportion (fair and deterministic — no code-level judgment call
        about which position "deserves" the remaining budget) rather than
        picking winners."""
        remaining_budget = self._settings.max_weekly_turnover - turnover_used_this_week
        if remaining_budget <= 0:
            for d in sized_decisions:
                if d.final_allocation != d.current_allocation:
                    d.final_allocation = d.current_allocation
                    d.turnover_capped = True
            return

        proposed_turnover = sum(abs(d.final_allocation - d.current_allocation) for d in sized_decisions)
        if proposed_turnover <= remaining_budget:
            return

        scale = remaining_budget / proposed_turnover
        for d in sized_decisions:
            delta = d.final_allocation - d.current_allocation
            if delta != 0:
                d.final_allocation = d.current_allocation + delta * scale
                d.turnover_capped = True
