"""Phase 5: single API-key header access control — a genuinely sufficient
minimum bar for this project's localhost/personal-machine-only deployment
scope (see doc/phases.md's Phase 5 section), not a stand-in for production
auth. Applied to every endpoint except the health check.
"""

from fastapi import Header, HTTPException

from app.config import Settings, get_settings

API_KEY_HEADER_NAME = "X-API-Key"


def verify_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER_NAME)) -> None:
    settings: Settings = get_settings()
    configured_key = settings.require_x_api_key()
    if x_api_key is None or x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
