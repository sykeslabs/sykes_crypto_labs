import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.database.evidence_provenance import group_observations_by_multi_entry_source
from app.database.models import Asset
from app.llm.adversarial_schemas import BearBatch, BullBatch
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset


@dataclass
class AssetResearchContext:
    asset: Asset
    screened: ScreenedAsset
    evidence_by_source: dict[str, dict] = field(default_factory=dict)
    # 3g fix: multi-entry per-asset sources (dated-futures term structure)
    # keep every distinct instrument, not one collapsed row.
    term_structure_by_source: dict[str, list] = field(default_factory=dict)
    assessments: list[ModelMarketAssessmentRecord] = field(default_factory=list)


@dataclass
class ResearchContext:
    run_id: str
    as_of: datetime
    regime: MarketRegimeSnapshot | None
    assets: list[AssetResearchContext]


def build_research_context(
    run_id: str,
    candidates: list[ScreenedAsset],
    assets_by_id: dict[str, Asset],
    regime_repo,
    evidence_repo,
    assessment_repo,
) -> ResearchContext:
    as_of = datetime.now(UTC)
    regime = regime_repo.get_latest()

    assessments_by_asset: dict[str, list[ModelMarketAssessmentRecord]] = {}
    for a in assessment_repo.get_latest_run_assessments():
        assessments_by_asset.setdefault(a.asset_id, []).append(a)

    asset_contexts = []
    for candidate in candidates:
        asset = assets_by_id.get(candidate.asset_id)
        if asset is None:
            continue
        single_obs, term_structure_obs = group_observations_by_multi_entry_source(
            evidence_repo.get_latest_by_asset(asset.id)
        )
        evidence_by_source: dict[str, dict] = {}
        for obs in single_obs:
            evidence_by_source.setdefault(obs.source, obs.payload)
        term_structure_by_source = {
            source: [obs.payload for obs in obs_list]
            for source, obs_list in term_structure_obs.items()
        }

        asset_contexts.append(AssetResearchContext(
            asset=asset, screened=candidate, evidence_by_source=evidence_by_source,
            term_structure_by_source=term_structure_by_source,
            assessments=assessments_by_asset.get(asset.id, []),
        ))

    return ResearchContext(run_id=run_id, as_of=as_of, regime=regime, assets=asset_contexts)


def _render_shared_asset_lines(context: ResearchContext) -> list[str]:
    lines = [f"As of: {context.as_of.isoformat()}"]
    if context.regime is not None:
        lines.append(f"Market regime (shared): {context.regime.regime}")
    lines.append("")
    for ac in context.assets:
        lines.append(f"## {ac.asset.symbol} ({ac.asset.name})")
        lines.append(f"Composite factor score (3b, deterministic): {ac.screened.composite_factor_score}")
        if ac.evidence_by_source:
            lines.append("Derivatives/on-chain evidence (3c):")
            for source, payload in ac.evidence_by_source.items():
                lines.append(f"  - {source}: {payload}")
        if ac.term_structure_by_source:
            for source, payloads in ac.term_structure_by_source.items():
                lines.append(
                    f"Futures term structure (3c), {source}, {len(payloads)} distinct "
                    f"dated instruments (the full curve, not one point):"
                )
                for payload in payloads:
                    lines.append(f"  - {payload}")
        if ac.assessments:
            lines.append("3d model assessments:")
            for a in ac.assessments:
                lines.append(
                    f"  - {a.provider}: overall={a.overall_assessment} thesis=\"{a.thesis}\""
                )
        lines.append("")
    return lines


BULL_SYSTEM_PROMPT_TEMPLATE = """\
You build the STRONGEST evidence-based bull case for each given crypto \
asset — valuation, adoption, ecosystem growth, and concrete catalysts. \
Reason only from the evidence given; never invent a source not present in \
the context. This is one asset's opening argument in an adversarial \
research cycle — a bear researcher will attack it next, so ground every \
catalyst/evidence item in something specific from the context, not vague \
optimism.

Respond with ONLY a single JSON object (no markdown fences, no commentary):

{{
  "cases": [
    {{"asset": "<symbol>", "thesis": "...", "catalysts": ["..."], "evidence": ["..."]}}
  ]
}}

Prompt version: {prompt_version}\
"""


def render_bull_prompt(context: ResearchContext, prompt_version: str) -> tuple[str, str]:
    system_prompt = BULL_SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)
    user_prompt = "\n".join(_render_shared_asset_lines(context))
    return system_prompt, user_prompt


BEAR_SYSTEM_PROMPT_TEMPLATE = """\
You are the BEAR researcher in an adversarial research cycle. For each \
asset you are given its own bull case — your job is to ATTACK that \
SPECIFIC thesis, not list generic crypto risks. Consider: tokenomics/\
unlocks, dilution, competition, leverage/positioning, regulatory risk, \
technical deterioration, and narrative exhaustion, but only raise points \
that genuinely undermine THIS asset's stated catalysts/evidence. For every \
attack point, name which bull catalyst or evidence item it rebuts in \
`attacks_bull_point` (verbatim or close paraphrase) — a bear case with no \
`attacks_bull_point` entries has failed at being adversarial.

Respond with ONLY a single JSON object (no markdown fences, no commentary):

{{
  "cases": [
    {{"asset": "<symbol>", "attack_points": ["..."], "evidence": ["..."], "attacks_bull_point": ["..."]}}
  ]
}}

Prompt version: {prompt_version}\
"""


def render_bear_prompt(context: ResearchContext, bull_batch: BullBatch, prompt_version: str) -> tuple[str, str]:
    system_prompt = BEAR_SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)
    lines = _render_shared_asset_lines(context)
    lines.append("## Bull cases to attack")
    for case in bull_batch.cases:
        lines.append(f"### {case.asset}")
        lines.append(f"Thesis: {case.thesis}")
        lines.append(f"Catalysts: {case.catalysts}")
        lines.append(f"Evidence: {case.evidence}")
        lines.append("")
    return system_prompt, "\n".join(lines)


SCENARIO_SYSTEM_PROMPT_TEMPLATE = """\
Given each asset's bull case and the bear case attacking it, build bull/\
base/bear SCENARIOS — each with probability, expected_return, price_target \
(if a concrete level is reasonable, else null), timeframe, assumptions, \
catalysts, and failure_conditions. The three scenarios' probabilities need \
not sum to exactly 1.0 but should be roughly complementary. Use whichever \
of 7d/30d/90d/180d/365d timeframes is most meaningful per scenario — they \
need not all share one timeframe.

Respond with ONLY a single JSON object (no markdown fences, no commentary):

{{
  "scenarios": [
    {{
      "asset": "<symbol>",
      "bull": {{"probability": 0.3, "expected_return": 0.5, "price_target": null, "timeframe": "90d", "assumptions": ["..."], "catalysts": ["..."], "failure_conditions": ["..."]}},
      "base": {{...}},
      "bear": {{...}}
    }}
  ]
}}

Prompt version: {prompt_version}\
"""


def render_scenario_prompt(
    context: ResearchContext, bull_batch: BullBatch, bear_batch: BearBatch, prompt_version: str
) -> tuple[str, str]:
    system_prompt = SCENARIO_SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)
    bear_by_asset = {c.asset: c for c in bear_batch.cases}
    lines = _render_shared_asset_lines(context)
    lines.append("## Bull/bear cases")
    for bull_case in bull_batch.cases:
        bear_case = bear_by_asset.get(bull_case.asset)
        lines.append(f"### {bull_case.asset}")
        lines.append(f"Bull thesis: {bull_case.thesis}")
        if bear_case:
            lines.append(f"Bear attack points: {bear_case.attack_points}")
        lines.append("")
    return system_prompt, "\n".join(lines)


def compute_template_hash(*templates: str) -> str:
    return hashlib.sha256("\n".join(templates).encode("utf-8")).hexdigest()
