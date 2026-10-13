"""Validated Brazilian retail price observations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class PriceOffer(BaseModel):
    """One observed standard-price offer for an exact new product."""

    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    identifier: str = Field(min_length=4)
    retailer: str = Field(min_length=2, max_length=100)
    source_url: HttpUrl
    price_brl: Decimal = Field(gt=0, le=1_000_000, decimal_places=2)
    observed_at: datetime
    condition: Literal["new"] = "new"
    payment: Literal["standard"] = "standard"

    @field_validator("observed_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """Store a timezone-aware UTC observation timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Observation time must include a timezone")
        return value.astimezone(UTC)
