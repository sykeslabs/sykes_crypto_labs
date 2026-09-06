from functools import lru_cache

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
    return create_client(url, key, options=ClientOptions(postgrest_client_timeout=SUPABASE_CLIENT_TIMEOUT_SECONDS))
