"""Orchestrates: parse file -> measure each feature -> persist."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import FileProcessingError
from app.models import Feature, FileStatus, MeasurementStatus, UploadedFile
from app.services.crs import crs_label
from app.services.measurement import measure_geometry
from app.services.readers import read_kml, read_shapefile_zip

log = logging.getLogger(__name__)

FILE_TYPES = {".kml": "kml", ".zip": "shapefile"}


def new_file_record(filename: str, ext: str, stored_path: Path) -> UploadedFile:
    return UploadedFile(
        id=uuid.uuid4().hex,
        filename=filename,
        file_type=FILE_TYPES[ext],
        status=FileStatus.PROCESSING.value,
        stored_path=str(stored_path),
    )


def process_file(db: Session, record: UploadedFile, settings: Settings) -> UploadedFile:
    """Parse + measure + persist. Marks the record COMPLETED or FAILED; never raises."""
    path = Path(record.stored_path)
    try:
        if record.file_type == "kml":
            parsed = read_kml(path)
        else:
            parsed = read_shapefile_zip(path, settings)

        features = []
        for pf in parsed.features:
            if pf.error:
                m_status, m_note = MeasurementStatus.ERROR, pf.error
                m = None
            else:
                m = measure_geometry(pf.geometry, parsed.crs)
                m_status, m_note = m.status, m.note
            features.append(
                Feature(
                    file_id=record.id,
                    feature_index=pf.index,
                    geometry_type=pf.geometry.geom_type if pf.geometry is not None else None,
                    geometry=mapping(pf.geometry) if pf.geometry is not None else None,
                    properties=pf.properties,
                    measurement_status=m_status.value,
                    measurement_crs=m.measurement_crs if m else None,
                    area_sq_m=m.area_sq_m if m else None,
                    perimeter_m=m.perimeter_m if m else None,
                    length_m=m.length_m if m else None,
                    is_valid=m.is_valid if m else None,
                    measurement_note=m_note,
                )
            )

        db.add_all(features)
        record.crs = crs_label(parsed.crs)
        record.feature_count = len(features)
        record.status = FileStatus.COMPLETED.value
    except FileProcessingError as exc:
        db.rollback()
        record.status = FileStatus.FAILED.value
        record.error_message = str(exc)
    except Exception:  # defensive: never leak internals, but do log them
        log.exception("Unexpected failure processing file %s", record.id)
        db.rollback()
        record.status = FileStatus.FAILED.value
        record.error_message = "Unexpected error while processing the file"

    db.add(record)
    db.commit()
    return record
