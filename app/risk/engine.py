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

# Tolerance for float-accumulation noise in `turnover_used_this_week`, a
# real sum of every real portfolio_allocation_changes row in the trailing
# week (app/database/repository.py's get_turnover_since) -- summing enough
# real floats can land a hair off the mathematically exact value (a real
# incident found live 2026-09-14: a week whose true turnover was exactly
# at MAX_WEEKLY_TURNOVER computed as 0.30000000000000004 against a 0.3 cap,
# a ~4e-17 error, which without this tolerance silently reverted every
# proposed position change that run -- not a crash, no error surfaced
# anywhere). Snapping any remaining-budget value within this tolerance of
# zero to exactly 0.0 makes the branch below fire on a genuine budget
# state, not representation noise, in EITHER direction -- this does not by
# itself change the outcome when the real remaining budget is genuinely
# ~0, only when noise would have pushed a genuinely-under-cap week over.
TURNOVER_EPSILON = 1e-9


@dataclass
class SizedDecision:
    asset_id: str
    symbol: str
    decision: DecisionValue
    original_decision: DecisionValue
    confidence: float
    # REAL, ground-truth holdings-based allocation (Phase 5a) -- used for
    # every real-risk gating decision below (is_new_position, the
    # rebalance-confidence bar, WATCH/NO_TRADE's "hold what you actually
    # have"). Never the turnover baseline -- see `previous_system_target`.
    current_allocation: float
    # The system's OWN last recorded target (portfolio_positions.current_allocation
    # before this run; 0.0 if this asset has never been targeted before --
    # genuine bootstrap). A real, previously-undiscovered bug (found live
    # 2026-09-14): the turnover cap used to measure proposed change against
    # `current_allocation` (real holdings) instead of this -- so a manual
    # `/holdings` trade that moved real holdings away from the system's own
    # last target got silently charged against the STRATEGY's turnover
    # budget the next time the Judge revisited that asset, often
    # repeatedly, every run, until the gap happened to close. See
    # `RiskEngine.apply_turnover_cap`'s own docstring for the real backtest
    # evidence (a real historical incident dropped from 51.33% to 5.33% of
    # "turnover" once measured against this baseline instead).
    previous_system_target: float
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
        previous_system_target: float,
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
            previous_system_target=previous_system_target,
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

    def remaining_turnover_budget(self, turnover_used_this_week: float) -> float:
        """The real, epsilon-snapped remaining weekly turnover budget --
        exposed so a caller (e.g. the TurnoverCapEvent logged when this
        cap fires) can report the exact same number `apply_turnover_cap`
        itself reasons from, rather than recomputing it separately and
        risking the two silently drifting apart."""
        remaining_budget = self._settings.max_weekly_turnover - turnover_used_this_week
        if abs(remaining_budget) <= TURNOVER_EPSILON:
            remaining_budget = 0.0
        return remaining_budget

    def _strategy_turnover_delta(self, d: SizedDecision) -> float:
        """The real quantity MAX_WEEKLY_TURNOVER should be measuring: how
        much the STRATEGY's own target changed, not how far real holdings
        happen to sit from the newest recommendation. WATCH/NO_TRADE are
        explicitly zero -- per PHASE3E_PROMPT.md's own framing these are
        not sizing decisions at all, so they can never move the system's
        own target, by construction (matches size_one's own
        `final_allocation = current_allocation` for these -- this method
        just makes that "no real change" property explicit for the
        turnover baseline rather than relying on it to fall out of a
        real-holdings comparison, which is exactly the confusion the
        2026-09-14 incident traced back to).

        A real bug fixed here (found live 2026-09-14, backtested against
        14 real historical runs): the previous version measured this delta
        against `d.current_allocation` (real, ground-truth holdings) --
        so a manual `/holdings` trade that moved real holdings away from
        the system's own last target got silently charged against the
        STRATEGY's own turnover budget the next time (and every subsequent
        time) the Judge revisited that asset, even though the strategy
        itself hadn't changed its mind at all. Real backtest evidence: total
        raw turnover across the same 14 real live runs was 318.30% measured
        the old way vs. 89.23% measured this way -- a 72% reduction
        entirely attributable to removing this double-counted external
        drift. The real incident that surfaced this (2026-09-13, BTC+SOL)
        measured 51.33% the old way vs. a genuine 5.33% this way, and would
        NOT have tripped the existing 7-day/30% cap at all under this fix
        -- see doc/operations.md's turnover section (or the dashboard TODO)
        for the full investigation. Real holdings still drive every actual
        RISK decision (is_new_position, the rebalance-confidence gate,
        WATCH's "hold what you actually have") via `current_allocation`,
        completely unchanged -- only the TURNOVER BUDGET's own baseline
        changes here."""
        if d.decision in ("WATCH", "NO_TRADE"):
            return 0.0
        return d.final_allocation - d.previous_system_target

    def apply_turnover_cap(
        self, sized_decisions: list[SizedDecision], turnover_used_this_week: float
    ) -> None:
        """Mutates `sized_decisions` in place: if this run's total proposed
        STRATEGY turnover (see `_strategy_turnover_delta`) would push the
        trailing-week total over MAX_WEEKLY_TURNOVER, scales every proposed
        CHANGE down by the same proportion (fair and deterministic — no
        code-level judgment call about which position "deserves" the
        remaining budget) rather than picking winners. Reverting/scaling
        moves each decision back toward its own `previous_system_target`,
        never toward real holdings -- a blocked/capped run is a true no-op
        (or partial move) on the system's OWN bookkeeping, regardless of
        what real holdings happen to be doing independently."""
        remaining_budget = self.remaining_turnover_budget(turnover_used_this_week)
        if remaining_budget <= 0:
            for d in sized_decisions:
                if self._strategy_turnover_delta(d) != 0:
                    d.final_allocation = d.previous_system_target
                    d.turnover_capped = True
            return

        proposed_turnover = sum(abs(self._strategy_turnover_delta(d)) for d in sized_decisions)
        if proposed_turnover <= remaining_budget:
            return

        scale = remaining_budget / proposed_turnover
        for d in sized_decisions:
            delta = self._strategy_turnover_delta(d)
            if delta != 0:
                d.final_allocation = d.previous_system_target + delta * scale
                d.turnover_capped = True
