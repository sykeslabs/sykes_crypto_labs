"""Phase 3i: entity-flow intelligence, custody/OTC flow (infeasible, see
below), and network usage + developer-activity fundamentals. Zero LLM
calls. Every raw observation is stored as-is — no directional signal
derived at the collector level, same rule as every prior evidence source.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.database.evidence_provenance import DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE
from app.database.repository import (
    AssetRepository,
    EvidenceObservationRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.market_data.etherscan import ERC20_CONTRACT_ADDRESS_BY_SYMBOL, EtherscanClient
from app.market_data.evidence_schemas import EvidenceObservation
from app.market_data.github_activity import PRIMARY_REPO_BY_SYMBOL, GitHubClient
from app.market_data.nansen import SMART_MONEY_CHAINS, NansenClient

logger = logging.getLogger("crypto_ai_portfolio.market_data")

# Task 1 feasibility: which of this project's real universe symbols sit on
# a Nansen smart-money-supported chain, as an ERC-20/SPL TOKEN (not a
# native chain coin — Nansen's netflow endpoint excludes native tokens by
# default, and per-native-token coverage wasn't verified live given credit
# scarcity, so native coins like BTC/SOL/BNB/HYPE are deliberately left out
# here rather than guessed at). Real, disclosed limitation — see README.
NANSEN_CHAIN_BY_SYMBOL: dict[str, str] = {
    "LINK": "ethereum", "UNI": "ethereum", "ENA": "ethereum",
    "JASMY": "ethereum", "STORJ": "ethereum", "ZRX": "ethereum", "ONDO": "ethereum",
    "BONK": "solana", "JTO": "solana",
}

NETWORK_USAGE_WINDOW_DAYS = 7
# Etherscan's real per-call cap for this action is much higher, but 1000
# keeps this a single, fast, free-tier-friendly call while giving enough
# headroom that most of this project's real ERC-20 assets' 7-day activity
# fits inside it — verified live not to be universally true (see
# `possibly_truncated` below), disclosed rather than silently assumed.
NETWORK_USAGE_FETCH_LIMIT = 1000
DEV_ACTIVITY_COMMIT_WINDOW_DAYS = 30


@dataclass
class AssetIntelligenceResult:
    entity_flow_assets: list[str] = field(default_factory=list)
    network_usage_assets: list[str] = field(default_factory=list)
    developer_activity_assets: list[str] = field(default_factory=list)
    source_status: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return (
            f"entity_flow_assets={self.entity_flow_assets} "
            f"network_usage_assets={self.network_usage_assets} "
            f"developer_activity_assets={self.developer_activity_assets}"
        )


class AssetIntelligenceService:
    def __init__(
        self,
        asset_repo: AssetRepository,
        screened_universe_repo: ScreenedUniverseRepository,
        evidence_repo: EvidenceObservationRepository,
        signal_source_repo: SignalSourceRepository,
        nansen_client: NansenClient,
        etherscan_client: EtherscanClient,
        github_client: GitHubClient,
    ) -> None:
        self._asset_repo = asset_repo
        self._screened_universe_repo = screened_universe_repo
        self._evidence_repo = evidence_repo
        self._signal_source_repo = signal_source_repo
        self._nansen = nansen_client
        self._etherscan = etherscan_client
        self._github = github_client

    def run(self, run_id: str) -> AssetIntelligenceResult:
        result = AssetIntelligenceResult()
        now = datetime.now(UTC)
        observations: list[EvidenceObservation] = []

        # --- ENTITY_FLOW_INTELLIGENCE: TOP_CANDIDATES only (Nansen's free
        # tier is credit-constrained — see README's Phase 3i section) ---
        entity_flow_status = "NOT_IMPLEMENTED"
        if self._nansen.is_configured:
            candidates = self._screened_universe_repo.get_latest_top_candidates()
            candidates_by_chain: dict[str, list] = {}
            for c in candidates:
                chain = NANSEN_CHAIN_BY_SYMBOL.get(c.symbol)
                if chain:
                    candidates_by_chain.setdefault(chain, []).append(c)

            assets_by_symbol = {a.symbol: a for a in self._asset_repo.get_active_assets()}
            any_call_succeeded = False
            for chain, chain_candidates in candidates_by_chain.items():
                rows = self._nansen.fetch_smart_money_netflow(chain)
                if rows is None:
                    continue
                any_call_succeeded = True
                rows_by_symbol = {r.get("token_symbol"): r for r in rows}
                for c in chain_candidates:
                    row = rows_by_symbol.get(c.symbol)
                    asset = assets_by_symbol.get(c.symbol)
                    if row is None or asset is None:
                        continue
                    observations.append(EvidenceObservation(
                        source="entity_flow_intelligence", asset_id=asset.id, scope="ASSET",
                        observation_timestamp=now, retrieval_timestamp=now,
                        freshness="RECENT",
                        decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["entity_flow_intelligence"],
                        status="OK",
                        payload={
                            "chain": chain,
                            "net_flow_24h_usd": row.get("net_flow_24h_usd"),
                            "net_flow_7d_usd": row.get("net_flow_7d_usd"),
                            "net_flow_30d_usd": row.get("net_flow_30d_usd"),
                            "trader_count": row.get("trader_count"),
                            "label_note": (
                                "entity/cohort labels are Nansen's own inference, "
                                "unverified by this project directly"
                            ),
                        },
                    ))
                    result.entity_flow_assets.append(c.symbol)
            entity_flow_status = "OK" if any_call_succeeded else "UNAVAILABLE"

        # --- NETWORK_FUNDAMENTALS_DEV_ACTIVITY, part 1: per-token network
        # usage (Etherscan, free tier — dailytx/network-wide stats need a
        # paid Pro tier, verified live; a per-token active-address/tx-count
        # proxy from tokentx does not) ---
        network_usage_status = "NOT_IMPLEMENTED"
        if self._etherscan.is_configured:
            active_assets = self._asset_repo.get_active_assets()
            by_symbol = {a.symbol: a for a in active_assets}
            any_network_call_succeeded = False
            cutoff = now - timedelta(days=NETWORK_USAGE_WINDOW_DAYS)
            for symbol, contract in ERC20_CONTRACT_ADDRESS_BY_SYMBOL.items():
                asset = by_symbol.get(symbol)
                if asset is None:
                    continue
                transfers = self._etherscan.fetch_token_transfers(contract, offset=NETWORK_USAGE_FETCH_LIMIT)
                if transfers is None:
                    continue
                any_network_call_succeeded = True
                recent = [t for t in transfers if int(t.get("timeStamp", 0)) >= cutoff.timestamp()]
                distinct_addresses = {t.get("from") for t in recent} | {t.get("to") for t in recent}
                # Honesty check: a single Etherscan call is capped at
                # NETWORK_USAGE_FETCH_LIMIT transfers. For a busy token, ALL
                # of them can fall inside the requested window, meaning the
                # real covered span is shorter than NETWORK_USAGE_WINDOW_DAYS
                # (there may be more, uncounted, activity further back within
                # the nominal window) -- this must be disclosed, not silently
                # presented as a true like-for-like N-day figure across
                # tokens of very different trading volume.
                covered_from_ts = int(recent[-1]["timeStamp"]) if recent else None
                actual_days_covered = (
                    (now.timestamp() - covered_from_ts) / 86400 if covered_from_ts else None
                )
                possibly_truncated = len(recent) == len(transfers) == NETWORK_USAGE_FETCH_LIMIT
                observations.append(EvidenceObservation(
                    source="network_fundamentals_usage", asset_id=asset.id, scope="ASSET",
                    observation_timestamp=now, retrieval_timestamp=now,
                    timeframe=f"{NETWORK_USAGE_WINDOW_DAYS}d",
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["network_fundamentals_usage"],
                    status="OK",
                    payload={
                        "requested_window_days": NETWORK_USAGE_WINDOW_DAYS,
                        "actual_window_days_covered": actual_days_covered,
                        "possibly_truncated": possibly_truncated,
                        "transfer_count": len(recent),
                        "distinct_active_addresses": len(distinct_addresses),
                        "note": (
                            "per-token proxy, not network-wide stats (Etherscan's "
                            "network-wide dailytx endpoint requires a paid Pro tier, "
                            "verified live). possibly_truncated=true means this token's "
                            f"real transfer volume exceeds the {NETWORK_USAGE_FETCH_LIMIT}"
                            "-per-call fetch limit, so actual_window_days_covered is "
                            "shorter than requested_window_days -- transfer_count/"
                            "distinct_active_addresses are a floor for that shorter "
                            "span, not a true N-day figure comparable across tokens "
                            "of different trading volume."
                        ),
                    },
                ))
                result.network_usage_assets.append(symbol)
            network_usage_status = "OK" if any_network_call_succeeded else "UNAVAILABLE"

        # --- NETWORK_FUNDAMENTALS_DEV_ACTIVITY, part 2: developer activity
        # (GitHub, free — curated unambiguous-primary-repo map only) ---
        active_assets = self._asset_repo.get_active_assets()
        by_symbol = {a.symbol: a for a in active_assets}
        any_dev_call_succeeded = False
        commit_since = now - timedelta(days=DEV_ACTIVITY_COMMIT_WINDOW_DAYS)
        for symbol, (owner, repo) in PRIMARY_REPO_BY_SYMBOL.items():
            asset = by_symbol.get(symbol)
            if asset is None:
                continue
            commit_count = self._github.fetch_commit_count_since(owner, repo, commit_since)
            contributor_count = self._github.fetch_contributor_count(owner, repo)
            if commit_count is None and contributor_count is None:
                continue
            any_dev_call_succeeded = True
            observations.append(EvidenceObservation(
                source="developer_activity", asset_id=asset.id, scope="ASSET",
                observation_timestamp=now, retrieval_timestamp=now,
                timeframe=f"{DEV_ACTIVITY_COMMIT_WINDOW_DAYS}d",
                freshness="RECENT",
                decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["developer_activity"],
                status="OK",
                payload={
                    "repo": f"{owner}/{repo}",
                    "window_days": DEV_ACTIVITY_COMMIT_WINDOW_DAYS,
                    "commit_count": commit_count,
                    "contributor_count": contributor_count,
                    "note": (
                        "a slow-moving, multi-month-to-multi-year fundamentals signal, "
                        "not a timing signal -- a short-term dip does not imply "
                        "abandonment"
                    ),
                },
            ))
            result.developer_activity_assets.append(symbol)

        dev_status_ok = any_dev_call_succeeded or network_usage_status == "OK"
        network_fundamentals_status = "OK" if dev_status_ok else "UNAVAILABLE"

        self._evidence_repo.insert_many(observations)

        result.source_status = {
            "ENTITY_FLOW_INTELLIGENCE": entity_flow_status,
            "CUSTODY_OTC_FLOW": "NOT_IMPLEMENTED",
            "NETWORK_FUNDAMENTALS_DEV_ACTIVITY": network_fundamentals_status,
        }
        source_notes = {
            "ENTITY_FLOW_INTELLIGENCE": (
                "Nansen's smart-money/netflow API, verified live (real free-tier "
                "auth + real per-token data confirmed). Free tier: 100 one-time "
                "credits + 10/day refill -- genuinely credit-constrained, so this "
                "covers TOP_CANDIDATES only, grouped by chain (one 5-credit call "
                "per distinct chain among candidates, not one per asset). Coverage "
                "gap: Nansen's smart-money chains are EVM/Solana only -- BTC and "
                "every native-chain coin (SOL, BNB, HYPE, etc.) are NOT covered "
                "(native tokens are also excluded by the endpoint's own default, "
                "unverified live given credit scarcity). Entity/cohort labels are "
                "Nansen's own inference, unverified by this project directly -- a "
                "labeled 'smart money' cohort accumulating is not a directional "
                "signal on its own. Arkham Intelligence investigated and found "
                "genuinely inaccessible (Cloudflare bot-challenge-gated on every "
                "path tried, same standard as CoinAnk in 3f)."
            ),
            "CUSTODY_OTC_FLOW": (
                "Investigated in 3i: no reliable, independently-verifiable source "
                "of real custody-provider wallet addresses (Coinbase Custody, "
                "Fidelity Digital Assets, etc.) exists -- unlike 3c's exchange "
                "hot-wallet proxy, these aren't in any official public registry. "
                "Building this would mean fabricating or guessing addresses, which "
                "this project does not do. A genuine infeasibility, not a failure."
            ),
            "NETWORK_FUNDAMENTALS_DEV_ACTIVITY": (
                f"Network usage: a per-token active-address/transfer-count proxy "
                f"from Etherscan's free tokentx endpoint (7 real, live-verified "
                f"ERC-20 contract addresses -- see ERC20_CONTRACT_ADDRESS_BY_SYMBOL), "
                f"NOT the network-wide dailytx stat (confirmed live: requires "
                f"Etherscan's separate paid Pro tier). Developer activity: real "
                f"GitHub commit/contributor counts for {len(PRIMARY_REPO_BY_SYMBOL)} "
                f"assets with an unambiguous primary repo; every other symbol in "
                f"the universe is closed-source, multi-repo, or has no core dev "
                f"team (meme/community tokens) and is marked UNAVAILABLE rather "
                f"than guessed, per this task's own instruction."
            ),
        }
        for name, status in result.source_status.items():
            self._signal_source_repo.update_status(name, status, notes=source_notes.get(name))

        return result
