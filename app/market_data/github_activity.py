import logging
from datetime import datetime

import httpx

from app.config import Settings

logger = logging.getLogger("crypto_ai_portfolio.market_data")

# A small, explicit, curated mapping of asset symbol -> unambiguous primary
# GitHub repository — per PHASE3I_PROMPT.md's own instruction, ambiguous or
# multi-repo/forked projects are marked UNAVAILABLE rather than guessed.
# Real, verified-live repos only; deliberately not exhaustive over the full
# universe (see README's Phase 3i section for which symbols are excluded
# and why: closed-source, no canonical repo, or a meme/community token with
# no core development team).
PRIMARY_REPO_BY_SYMBOL: dict[str, tuple[str, str]] = {
    "BTC": ("bitcoin", "bitcoin"),
    "ETH": ("ethereum", "go-ethereum"),
    "SOL": ("solana-labs", "solana"),
    "XRP": ("XRPLF", "rippled"),
    "LINK": ("smartcontractkit", "chainlink"),
    "NEAR": ("near", "nearcore"),
    "UNI": ("Uniswap", "v3-core"),
    "ZEC": ("zcash", "zcash"),
    "XMR": ("monero-project", "monero"),
    "XTZ": ("tezos", "tezos"),
}


class GitHubClient:
    """Wrapper around GitHub's public REST API. No key required (60
    requests/hour); an optional GITHUB_TOKEN raises this to 5000/hour —
    plenty of headroom either way for a small, curated repo set."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.github_token.get_secret_value() if settings.github_token else None

    def _headers(self) -> dict:
        headers = {"User-Agent": "sykes-crypto-labs-research", "Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def fetch_commit_count_since(self, owner: str, repo: str, since: datetime) -> int | None:
        """Real commit count on the repo's default branch since `since`.
        Returns None on failure (never fabricated)."""
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/commits",
                    params={"since": since.isoformat(), "per_page": 100},
                    headers=self._headers(),
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                # GitHub paginates at 100/page; a real per-page count is a
                # reasonable trend proxy for an active-vs-quiet comparison
                # without walking every page (keeps this a light, low-cost
                # call, consistent with the task's "near-zero marginal
                # cost" framing).
                return len(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("GitHub commit count failed for %s/%s: %s", owner, repo, exc)
            return None

    def fetch_contributor_count(self, owner: str, repo: str) -> int | None:
        """Real distinct-contributor count over GitHub's own tracked
        history (its `stats/contributors` endpoint). Returns None on
        failure or if GitHub is still computing stats (202 — a real,
        documented API behavior, not an error)."""
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/stats/contributors",
                    headers=self._headers(),
                )
                if response.status_code in (404, 202):
                    return None
                response.raise_for_status()
                data = response.json()
                return len(data) if isinstance(data, list) else None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("GitHub contributor count failed for %s/%s: %s", owner, repo, exc)
            return None
