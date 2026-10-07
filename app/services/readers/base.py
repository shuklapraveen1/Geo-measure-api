from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pyproj import CRS
from shapely.geometry.base import BaseGeometry


@dataclass
class ParsedFeature:
    index: int
    geometry: BaseGeometry | None
    properties: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # per-feature parse problem (feature is kept, flagged)


@dataclass
class ParsedFile:
    crs: CRS
    features: list[ParsedFeature]


def json_safe(value: Any) -> Any:
    """Coerce attribute values (dates, Decimals, bytes, NaN...) into JSON-friendly types."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value
