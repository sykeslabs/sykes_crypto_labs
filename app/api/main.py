"""Phase 5: FastAPI read/query layer over the Evidence Store. Localhost/
personal-machine deployment scope only (see README's Phase 5 section) — a
single API-key header is the access-control mechanism, documented as a
minimum bar, not production-grade auth.

Run locally:
    uvicorn app.api.main:app --host 127.0.0.1 --port 8000
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.routers import assessments, calibration, cost, holdings, judge, portfolio, screening, signal_sources

logger = logging.getLogger("crypto_ai_portfolio.api")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Crypto AI Portfolio — Read/Query API")

app.include_router(screening.router)
app.include_router(assessments.router)
app.include_router(judge.router)
app.include_router(portfolio.router)
app.include_router(calibration.router)
app.include_router(signal_sources.router)
app.include_router(cost.router)
app.include_router(holdings.router)


@app.get("/health")
def health() -> dict:
    """The one endpoint that does NOT require the API key."""
    return {"status": "ok"}


@app.get("/")
def dashboard() -> FileResponse:
    """The static dashboard shell — no API key required to load the page
    itself (it contains no data), but every data-bearing fetch() call it
    makes client-side goes through the same `X-API-Key`-gated JSON
    endpoints as any other caller."""
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """A hardcoded, generic error body on any unhandled exception — never
    the exception's own message/traceback, which could otherwise leak a
    configured secret embedded in a lower-level client's error string
    (Supabase, httpx, etc.). Logged server-side (not client-reachable) for
    real debugging."""
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
