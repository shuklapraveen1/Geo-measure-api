"""ORM models: an uploaded file and the features extracted from it."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FileStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementStatus(str, enum.Enum):
    OK = "OK"  # area/length computed
    NOT_REQUIRED = "NOT_REQUIRED"  # e.g. Point - nothing to measure
    UNSUPPORTED = "UNSUPPORTED"  # geometry type/emptiness we can't measure
    ERROR = "ERROR"  # something went wrong for this one feature


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadedFile(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))  # "kml" | "shapefile"
    status: Mapped[str] = mapped_column(String(16), default=FileStatus.PROCESSING.value)
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stored_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="Feature.feature_index"
    )


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (Index("ix_features_file_idx", "file_id", "feature_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    feature_index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON, in the file's CRS
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    measurement_status: Mapped[str] = mapped_column(String(16))
    measurement_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    area_sq_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    perimeter_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    measurement_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped[UploadedFile] = relationship(back_populates="features")
