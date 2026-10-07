from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None
    status: str
    error_message: str | None = None
    geometry_type_counts: dict[str, int] = {}
    created_at: datetime


class FileList(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[FileInfo]


class FeatureOut(BaseModel):
    feature_id: int
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    properties: dict[str, Any]


class FeatureList(BaseModel):
    file_id: str
    crs: str | None
    total: int
    limit: int
    offset: int
    results: list[FeatureOut]


class MeasurementOut(BaseModel):
    feature_id: int
    geometry_type: str | None
    status: str
    measurement_crs: str | None
    area_sq_m: float | None
    area_hectares: float | None
    perimeter_m: float | None
    length_m: float | None
    is_valid: bool | None
    note: str | None


class MeasurementSummary(BaseModel):
    total_area_sq_m: float
    total_length_m: float
    status_counts: dict[str, int]


class MeasurementList(BaseModel):
    file_id: str
    crs: str | None
    summary: MeasurementSummary
    total: int
    limit: int
    offset: int
    results: list[MeasurementOut]
