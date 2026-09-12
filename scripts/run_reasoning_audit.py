"""Phase 3g task 5: Judge reasoning audit.

Samples resolved decisions (weighted toward requires_review=true, low
model/source agreement, and outcome-contradicted-decision cases — see
`app.benchmarks.reasoning_audit.select_audit_sample`), and for each, a single
structured LLM call checks whether the decision's own stored thesis actually
follows from its own cited key_evidence/contradictory_evidence. Gated through
CostGuard like any other LLM-calling stage; persists to
`judge_reasoning_audits` (registered in COST_TRACKED_TABLES).

Only ever samples resolved BACKFILLED decisions (never live ones -- a
fixed, non-growing pool), and excludes decisions already audited in a
previous run -- safe to re-run repeatedly to expand coverage over time,
never re-auditing (and re-billing for) the same decision twice.

Usage:
    python -m scripts.run_reasoning_audit --sample-size 8 [--dry-run]
"""

import argparse
import hashlib
import sys
from datetime import UTC, datetime

from app.benchmarks.reasoning_audit import (
    AuditCandidate,
    render_audit_prompt,
    select_audit_sample,
)
from app.benchmarks.schemas import JudgeReasoningAuditRecord, ReasoningAuditResult
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import JudgeReasoningAuditRepository, PromptTemplateRepository
from app.llm.cost import CostGuard, CostLedgerRepository
from app.llm.structured_provider import OpenRouterStructuredProvider

PROMPT_TEMPLATE_NAME = "judge_reasoning_audit"
PROMPT_TEMPLATE_STAGE = "3g"
PROMPT_VERSION = "v1"


def fetch_candidates(client) -> list[AuditCandidate]:
    decisions = (
        client.table("judge_decisions")
        .select("id,decision,thesis,key_evidence,contradictory_evidence,requires_review,model_agreement,source_agreement")
        .eq("is_backfilled", True)
        .execute()
        .data
    )
    decision_ids = [d["id"] for d in decisions]
    if not decision_ids:
        return []
    outcomes = (
        client.table("decision_outcomes")
        .select("decision_id,realized_return,outcome_label")
        .in_("decision_id", decision_ids)
        .neq("outcome_label", "UNRESOLVED")
        .execute()
        .data
    )
    outcome_by_decision = {o["decision_id"]: o for o in outcomes}

    # Phase 5b addendum: exclude decisions already audited in a previous
    # run. This candidate pool (resolved backfilled decisions) is fixed --
    # it doesn't grow the way live decisions do -- and select_audit_sample's
    # own priority ranking is deterministic, so without this a repeated run
    # would just re-audit the same top-priority decisions over and over at
    # real LLM cost, with zero new coverage.
    already_audited = {
        row["decision_id"]
        for row in client.table("judge_reasoning_audits").select("decision_id").in_("decision_id", decision_ids).execute().data
    }

    candidates = []
    for d in decisions:
        if d["id"] in already_audited:
            continue
        outcome = outcome_by_decision.get(d["id"])
        if outcome is None:
            continue  # unresolved — nothing to weight "contradicted outcome" against yet
        rr = outcome["realized_return"]
        contradicted = (
            (d["decision"] == "BUY" and rr is not None and rr < 0)
            or (d["decision"] == "SELL" and rr is not None and rr > 0)
        )
        candidates.append(AuditCandidate(
            decision_id=d["id"],
            thesis=d["thesis"] or "",
            key_evidence=d["key_evidence"] or [],
            contradictory_evidence=d["contradictory_evidence"] or [],
            requires_review=bool(d["requires_review"]),
            model_agreement=d["model_agreement"],
            source_agreement=d["source_agreement"],
            outcome_contradicted_decision=contradicted,
        ))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="3g task 5: Judge reasoning audit")
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="Select and print the sample without calling the LLM.")
    args = parser.parse_args()

    settings = get_settings()
    client = get_supabase_client()

    candidates = fetch_candidates(client)
    print(f"Resolved backfilled decisions available to sample (excluding already-audited): {len(candidates)}")
    sample = select_audit_sample(candidates, args.sample_size)
    print(f"Selected {len(sample)} for audit:")
    for c in sample:
        print(
            f"  decision_id={c.decision_id} requires_review={c.requires_review} "
            f"model_agreement={c.model_agreement} source_agreement={c.source_agreement} "
            f"outcome_contradicted={c.outcome_contradicted_decision}"
        )
    if args.dry_run or not sample:
        return 0

    api_key, model = settings.require_reasoning_audit()
    provider = OpenRouterStructuredProvider(
        name="reasoning_audit", model=model, api_key=api_key,
        base_url=settings.openrouter_base_url, timeout_seconds=60.0,
    )
    cost_guard = CostGuard(settings, CostLedgerRepository(client))
    audit_repo = JudgeReasoningAuditRepository(client)
    prompt_template_repo = PromptTemplateRepository(client)
    template_hash = hashlib.sha256(PROMPT_VERSION.encode("utf-8")).hexdigest()
    prompt_template_repo.get_or_create(PROMPT_TEMPLATE_NAME, PROMPT_TEMPLATE_STAGE, PROMPT_VERSION, template_hash)

    results = []
    for c in sample:
        allowed, reason = cost_guard.check()
        if not allowed:
            print(f"Stopping — cost cap reached: {reason}")
            break

        system_prompt, user_prompt = render_audit_prompt(c, PROMPT_VERSION)
        call = provider.call(system_prompt, user_prompt, ReasoningAuditResult)
        if call.error is not None or call.parsed is None:
            print(f"  decision_id={c.decision_id}: FAILED ({call.error}), cost=${call.estimated_cost}")
            continue

        record = JudgeReasoningAuditRecord(
            run_at=datetime.now(UTC), decision_id=c.decision_id, audit_model=model,
            supported=call.parsed.supported, unsupported_claims=call.parsed.unsupported_claims,
            notes=call.parsed.notes, estimated_cost=call.estimated_cost, created_at=datetime.now(UTC),
        )
        audit_repo.insert(record)
        results.append(record)
        print(
            f"  decision_id={c.decision_id}: supported={record.supported} "
            f"unsupported_claims={record.unsupported_claims} cost=${call.estimated_cost}"
        )

    if results:
        unsupported_count = sum(1 for r in results if not r.supported)
        total_cost = sum(r.estimated_cost for r in results)
        print(f"\n=== Summary: {unsupported_count} of {len(results)} audited decisions show at least one unsupported claim ===")
        print(f"Total real cost this run: ${total_cost}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
