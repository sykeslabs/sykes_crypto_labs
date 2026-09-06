"""Phase 3g task 5: Judge reasoning audit. Formalizes 3f's manual spot-check
(README's Phase 3f section) into a persisted, repeatable check — one
structured LLM call per sampled decision, given ONLY that decision's stored
`thesis`/`key_evidence`/`contradictory_evidence` (never the live evidence
itself, which may have since decayed or been revised — the audit judges
whether the THESIS AS WRITTEN follows from the evidence AS CITED, a pure
internal-consistency check).
"""

from dataclasses import dataclass


@dataclass
class AuditCandidate:
    decision_id: str
    thesis: str
    key_evidence: list[str]
    contradictory_evidence: list[str]
    requires_review: bool
    model_agreement: float | None
    source_agreement: float | None
    outcome_contradicted_decision: bool


def select_audit_sample(candidates: list[AuditCandidate], sample_size: int) -> list[AuditCandidate]:
    """Weighted toward the cases PHASE3G_PROMPT.md task 5 calls out:
    `requires_review=true`, low model/source agreement, and cases where the
    outcome contradicted the decision — in that priority order, since a
    contradicted outcome is the rarest and most diagnostically valuable
    category. Deduplicates (a candidate matching multiple criteria is only
    included once) and never exceeds `sample_size`, even if fewer
    candidates qualify."""
    ranked: list[AuditCandidate] = []
    seen: set[str] = set()

    def _add(group: list[AuditCandidate]) -> None:
        for c in group:
            if c.decision_id not in seen:
                ranked.append(c)
                seen.add(c.decision_id)

    _add([c for c in candidates if c.outcome_contradicted_decision])
    _add([c for c in candidates if c.requires_review])
    _add([
        c for c in candidates
        if (c.model_agreement is not None and c.model_agreement < 0.6)
        or (c.source_agreement is not None and c.source_agreement < 0.6)
    ])
    _add(candidates)  # fill any remainder from the general pool, still deduped

    return ranked[:sample_size]


SYSTEM_PROMPT_TEMPLATE = """\
You are auditing ONE prior decision from a paper-trading crypto research \
system for internal reasoning consistency — NOT re-evaluating whether the \
decision was a good trade, and NOT using any evidence beyond what is given \
below (the live evidence behind this decision may have since decayed, been \
revised, or resolved differently; that is irrelevant to this audit).

Given only the decision's stored thesis and its own cited key_evidence and \
contradictory_evidence, determine: does the thesis actually follow from the \
cited key_evidence, and does it fairly address the cited \
contradictory_evidence — or does it contain an unsupported leap (a claim \
not actually backed by anything in key_evidence, or a contradiction it \
silently ignores rather than addresses)?

Respond with ONLY a single JSON object (no markdown fences, no commentary):

{{
  "supported": true|false,
  "unsupported_claims": ["<a specific claim in the thesis not backed by the cited evidence, or a contradiction it ignores>", "..."],
  "notes": "<brief, one or two sentences>"
}}

Prompt version: {prompt_version}\
"""


def render_audit_prompt(candidate: AuditCandidate, prompt_version: str) -> tuple[str, str]:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)
    lines = [
        f"Thesis: {candidate.thesis}",
        f"Key evidence cited: {candidate.key_evidence}",
        f"Contradictory evidence cited: {candidate.contradictory_evidence}",
    ]
    return system_prompt, "\n".join(lines)
