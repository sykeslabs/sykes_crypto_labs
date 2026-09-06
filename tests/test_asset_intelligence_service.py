from datetime import UTC, datetime

from app.database.models import Asset
from app.market_data.asset_intelligence_service import AssetIntelligenceService
from app.market_data.screening_schemas import ScreenedAsset


def _asset(symbol, asset_id=None):
    return Asset(
        id=asset_id or f"id-{symbol}", symbol=symbol, name=symbol, coingecko_id=symbol.lower(),
        active=True, in_asset=True, created_at=datetime.now(UTC),
    )


def _screened(symbol, asset_id=None):
    return ScreenedAsset(
        run_id="RUN-1", computed_at=datetime.now(UTC), symbol=symbol, coingecko_id=symbol.lower(),
        asset_id=asset_id or f"id-{symbol}", composite_factor_score=0.6, volatility_30d=0.02,
        is_top_candidate=True,
    )


class FakeAssetRepo:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeScreenedUniverseRepo:
    def __init__(self, candidates):
        self._candidates = candidates

    def get_latest_top_candidates(self):
        return self._candidates


class FakeEvidenceRepo:
    def __init__(self):
        self.inserted = []

    def insert_many(self, observations):
        self.inserted.extend(observations)


class FakeSignalSourceRepo:
    def __init__(self):
        self.statuses = {}
        self.notes = {}

    def update_status(self, name, status, notes=None):
        self.statuses[name] = status
        self.notes[name] = notes


class FakeNansenClient:
    def __init__(self, configured=True, rows_by_chain=None):
        self._configured = configured
        self._rows_by_chain = rows_by_chain or {}

    @property
    def is_configured(self):
        return self._configured

    def fetch_smart_money_netflow(self, chain, per_page=100):
        return self._rows_by_chain.get(chain)


class FakeEtherscanClient:
    def __init__(self, configured=True, transfers_by_contract=None):
        self._configured = configured
        self._transfers = transfers_by_contract or {}

    @property
    def is_configured(self):
        return self._configured

    def fetch_token_transfers(self, contract_address, chain_id=1, offset=200):
        return self._transfers.get(contract_address)


class FakeGitHubClient:
    def __init__(self, commit_counts=None, contributor_counts=None):
        self._commits = commit_counts or {}
        self._contributors = contributor_counts or {}

    def fetch_commit_count_since(self, owner, repo, since):
        return self._commits.get((owner, repo))

    def fetch_contributor_count(self, owner, repo):
        return self._contributors.get((owner, repo))


def _make_service(assets, candidates=None, nansen=None, etherscan=None, github=None, signal_repo=None):
    return AssetIntelligenceService(
        asset_repo=FakeAssetRepo(assets),
        screened_universe_repo=FakeScreenedUniverseRepo(candidates or []),
        evidence_repo=FakeEvidenceRepo(),
        signal_source_repo=signal_repo or FakeSignalSourceRepo(),
        nansen_client=nansen or FakeNansenClient(configured=False),
        etherscan_client=etherscan or FakeEtherscanClient(configured=False),
        github_client=github or FakeGitHubClient(),
    )


# --- ENTITY_FLOW_INTELLIGENCE --------------------------------------------------

def test_entity_flow_not_implemented_when_nansen_unconfigured():
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([_asset("ENA")], signal_repo=signal_repo, nansen=FakeNansenClient(configured=False))
    result = service.run("RUN-1")
    assert result.entity_flow_assets == []
    assert signal_repo.statuses["ENTITY_FLOW_INTELLIGENCE"] == "NOT_IMPLEMENTED"


def test_entity_flow_captures_real_matched_candidate_by_symbol():
    ena = _asset("ENA", "a1")
    candidates = [_screened("ENA", "a1")]
    nansen = FakeNansenClient(rows_by_chain={
        "ethereum": [{"token_symbol": "ENA", "net_flow_7d_usd": 482390.8, "trader_count": 8}],
    })
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([ena], candidates=candidates, nansen=nansen, signal_repo=signal_repo)
    result = service.run("RUN-1")
    assert result.entity_flow_assets == ["ENA"]
    assert signal_repo.statuses["ENTITY_FLOW_INTELLIGENCE"] == "OK"


def test_entity_flow_skips_candidate_not_on_a_nansen_supported_chain():
    # BTC has no entry in NANSEN_CHAIN_BY_SYMBOL -- a real, disclosed gap.
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    nansen = FakeNansenClient(rows_by_chain={"ethereum": []})
    service = _make_service([btc], candidates=candidates, nansen=nansen)
    result = service.run("RUN-1")
    assert result.entity_flow_assets == []


def test_entity_flow_unavailable_when_all_chain_calls_fail():
    ena = _asset("ENA", "a1")
    candidates = [_screened("ENA", "a1")]
    nansen = FakeNansenClient(rows_by_chain={"ethereum": None})  # call failed
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([ena], candidates=candidates, nansen=nansen, signal_repo=signal_repo)
    service.run("RUN-1")
    assert signal_repo.statuses["ENTITY_FLOW_INTELLIGENCE"] == "UNAVAILABLE"


# --- NETWORK_FUNDAMENTALS_DEV_ACTIVITY (network usage) -------------------------

def test_network_usage_not_implemented_when_etherscan_unconfigured():
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([_asset("LINK")], signal_repo=signal_repo, etherscan=FakeEtherscanClient(configured=False))
    result = service.run("RUN-1")
    assert result.network_usage_assets == []


def test_network_usage_computes_distinct_active_addresses_from_real_transfer_shape():
    from app.market_data.etherscan import ERC20_CONTRACT_ADDRESS_BY_SYMBOL

    link = _asset("LINK", "a1")
    link_contract = ERC20_CONTRACT_ADDRESS_BY_SYMBOL["LINK"]
    now_ts = int(datetime.now(UTC).timestamp())
    transfers = [
        {"timeStamp": str(now_ts), "from": "0xaaa", "to": "0xbbb"},
        {"timeStamp": str(now_ts), "from": "0xbbb", "to": "0xccc"},
    ]
    etherscan = FakeEtherscanClient(transfers_by_contract={link_contract: transfers})
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([link], etherscan=etherscan, signal_repo=signal_repo)
    result = service.run("RUN-1")
    assert result.network_usage_assets == ["LINK"]
    assert signal_repo.statuses["NETWORK_FUNDAMENTALS_DEV_ACTIVITY"] == "OK"
    obs = next(o for o in service._evidence_repo.inserted if o.source == "network_fundamentals_usage")
    assert obs.payload["distinct_active_addresses"] == 3  # aaa, bbb, ccc
    assert obs.payload["transfer_count"] == 2
    assert obs.payload["possibly_truncated"] is False


def test_network_usage_flags_possibly_truncated_for_a_busy_token():
    # Real bug found during live verification: a busy token's entire fetch
    # batch can fall within the requested window, meaning the real covered
    # span is shorter than NETWORK_USAGE_WINDOW_DAYS -- this must be
    # flagged, not silently presented as a true N-day figure.
    from app.market_data.asset_intelligence_service import NETWORK_USAGE_FETCH_LIMIT
    from app.market_data.etherscan import ERC20_CONTRACT_ADDRESS_BY_SYMBOL

    link = _asset("LINK", "a1")
    link_contract = ERC20_CONTRACT_ADDRESS_BY_SYMBOL["LINK"]
    now_ts = int(datetime.now(UTC).timestamp())
    # Every fetched transfer (up to the fetch limit) falls inside the window.
    transfers = [
        {"timeStamp": str(now_ts), "from": f"0x{i}", "to": f"0x{i + 1}"}
        for i in range(NETWORK_USAGE_FETCH_LIMIT)
    ]
    etherscan = FakeEtherscanClient(transfers_by_contract={link_contract: transfers})
    service = _make_service([link], etherscan=etherscan)
    service.run("RUN-1")
    obs = next(o for o in service._evidence_repo.inserted if o.source == "network_fundamentals_usage")
    assert obs.payload["possibly_truncated"] is True
    assert obs.payload["transfer_count"] == NETWORK_USAGE_FETCH_LIMIT


# --- NETWORK_FUNDAMENTALS_DEV_ACTIVITY (developer activity) --------------------

def test_developer_activity_captures_real_commit_and_contributor_counts():
    from app.market_data.github_activity import PRIMARY_REPO_BY_SYMBOL

    btc = _asset("BTC", "a1")
    owner, repo = PRIMARY_REPO_BY_SYMBOL["BTC"]
    github = FakeGitHubClient(
        commit_counts={(owner, repo): 42}, contributor_counts={(owner, repo): 15},
    )
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([btc], github=github, signal_repo=signal_repo)
    result = service.run("RUN-1")
    assert result.developer_activity_assets == ["BTC"]
    obs = next(o for o in service._evidence_repo.inserted if o.source == "developer_activity")
    assert obs.payload["commit_count"] == 42
    assert obs.payload["contributor_count"] == 15


def test_developer_activity_skips_symbols_without_a_curated_primary_repo():
    # A symbol genuinely absent from PRIMARY_REPO_BY_SYMBOL (ambiguous/
    # closed-source/meme token) must not appear in results at all.
    made_up = _asset("NOTAREALTOKEN", "a1")
    service = _make_service([made_up])
    result = service.run("RUN-1")
    assert result.developer_activity_assets == []


# --- CUSTODY_OTC_FLOW / signal_sources reaffirmation ---------------------------

def test_custody_otc_flow_always_not_implemented():
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([_asset("BTC")], signal_repo=signal_repo)
    service.run("RUN-1")
    assert signal_repo.statuses["CUSTODY_OTC_FLOW"] == "NOT_IMPLEMENTED"
    assert "custody" in signal_repo.notes["CUSTODY_OTC_FLOW"].lower()


def test_reaffirms_all_three_signal_sources_every_run():
    signal_repo = FakeSignalSourceRepo()
    service = _make_service([_asset("BTC")], signal_repo=signal_repo)
    service.run("RUN-1")
    assert set(signal_repo.statuses.keys()) == {
        "ENTITY_FLOW_INTELLIGENCE", "CUSTODY_OTC_FLOW", "NETWORK_FUNDAMENTALS_DEV_ACTIVITY",
    }
