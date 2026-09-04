from datetime import datetime

from pydantic import BaseModel


class Asset(BaseModel):
    id: str
    symbol: str
    name: str
    coingecko_id: str
    active: bool
    in_asset: bool
    created_at: datetime
