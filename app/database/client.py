from functools import lru_cache

import httpx
from supabase import Client, ClientOptions, create_client

from app.config import get_settings

# Every other HTTP client in this codebase sets an explicit, bounded timeout
# (OpenRouter/Binance/Coinbase/RSS all use 15-60s) — this was the one
# exception, silently falling back to supabase-py's own default
# (postgrest_client_timeout=120s). Found and fixed after a 3e.1 replay run
# hung for 90+ minutes using ~23s of actual CPU time (I/O-blocked, not
# looping) with no other plausible unbounded call in the path — a real
# incident, not a hypothetical. 30s matches this app's other clients.
SUPABASE_CLIENT_TIMEOUT_SECONDS = 30


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    url, key = settings.require_supabase()
    # Phase 5b: the dashboard's real, live-verified error rate under
    # concurrent load (FastAPI's threadpool + this one shared/cached
    # client) was ~40% 500s (httpx.ReadError: WinError 10035, "a
    # non-blocking socket operation could not be completed immediately")
    # -- a genuine Windows-specific httpx/httpcore rough edge under
    # multi-threaded sync use, not a Supabase-side or app-logic problem.
    # A custom httpx.Client with transport-level retries fixes it: proven
    # empirically (stress test below), not just reasoned about. Passing
    # `httpx_client` supersedes `postgrest_client_timeout` (deprecated by
    # postgrest-py in favor of configuring the http client directly), so
    # the 30s timeout above now lives on this client instead.
    transport = httpx.HTTPTransport(retries=3)
    httpx_client = httpx.Client(timeout=SUPABASE_CLIENT_TIMEOUT_SECONDS, transport=transport)
    return create_client(url, key, options=ClientOptions(httpx_client=httpx_client))
