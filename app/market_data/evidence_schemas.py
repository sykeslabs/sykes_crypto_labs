from datetime import datetime

from pydantic import BaseModel

from app.database.evidence_provenance import EvidenceStatus, Freshness, Scope


class EvidenceObservation(BaseModel):
    """One row of `evidence_observations` — the shared shape from 3a
    (app/database/evidence_provenance.py) applied to a concrete table.
    Reused across every 3c/3f source rather than one table per source."""

    id: str | None = None
    source: str
    asset_id: str | None = None
    scope: Scope
    observation_timestamp: datetime
    publication_timestamp: datetime | None = None
    retrieval_timestamp: datetime
    timeframe: str | None = None
    is_revision_of: str | None = None
    freshness: Freshness | None = None
    decay_half_life_hours: float | None = None
    status: EvidenceStatus
    payload: dict = {}

    def to_row(self) -> dict:
        return {
            "source": self.source,
            "asset_id": self.asset_id,
            "scope": self.scope,
            "observation_timestamp": self.observation_timestamp.isoformat(),
            "publication_timestamp": (
                self.publication_timestamp.isoformat() if self.publication_timestamp else None
            ),
            "retrieval_timestamp": self.retrieval_timestamp.isoformat(),
            "timeframe": self.timeframe,
            "is_revision_of": self.is_revision_of,
            "freshness": self.freshness,
            "decay_half_life_hours": self.decay_half_life_hours,
            "status": self.status,
            "payload": self.payload,
        }
