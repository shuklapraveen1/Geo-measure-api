from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Feature, FileStatus, UploadedFile
from app.schemas import (
    FeatureList,
    FeatureOut,
    FileInfo,
    FileList,
    MeasurementList,
    MeasurementOut,
    MeasurementSummary,
)
from app.services.processing import FILE_TYPES, new_file_record, process_file

router = APIRouter(prefix="/api/files", tags=["files"])

CHUNK = 1024 * 1024


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File '{file_id}' not found")
    return record


def _file_info(db: Session, record: UploadedFile) -> FileInfo:
    rows = db.execute(
        select(Feature.geometry_type, func.count())
        .where(Feature.file_id == record.id)
        .group_by(Feature.geometry_type)
    ).all()
    info = FileInfo.model_validate(record)
    info.geometry_type_counts = {(t or "None"): n for t, n in rows}
    return info


def _safe_name(name: str) -> str:
    name = Path(name).name  # drop any directory components
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:200] or "upload"


@router.post("/", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: UploadFile = File(..., description="A .kml file or a .zip containing a Shapefile"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Upload and synchronously process a KML or zipped Shapefile."""
    original_name = Path(file.filename or "").name
    ext = Path(original_name).suffix.lower()
    if ext not in FILE_TYPES:
        hint = " Zip the .shp/.shx/.dbf/.prj files together." if ext == ".shp" else ""
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type '{ext or 'none'}'. Upload a .kml or a .zip containing a Shapefile.{hint}",
        )

    # Persist the upload to disk (streamed, size-capped).
    probe = new_file_record(original_name, ext, Path())
    dest_dir = settings.upload_dir / probe.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_name(original_name)
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        413,
                        f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit",
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    except HTTPException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    probe.stored_path = str(dest)
    db.add(probe)
    db.commit()  # visible as PROCESSING before work starts

    record = process_file(db, probe, settings)
    info = _file_info(db, record)
    if record.status == FileStatus.FAILED.value:
        return JSONResponse(
            status_code=422,
            content={
                "detail": record.error_message,
                "file": info.model_dump(mode="json"),
            },
        )
    return info


@router.get("/", response_model=FileList)
def list_files(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(UploadedFile)) or 0
    rows = db.scalars(
        select(UploadedFile).order_by(UploadedFile.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return FileList(
        total=total, limit=limit, offset=offset, results=[_file_info(db, r) for r in rows]
    )


@router.get("/{file_id}/", response_model=FileInfo)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _file_info(db, _get_file_or_404(db, file_id))


@router.delete("/{file_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    file_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    record = _get_file_or_404(db, file_id)
    db.delete(record)
    db.commit()
    shutil.rmtree(settings.upload_dir / file_id, ignore_errors=True)


@router.get("/{file_id}/features/", response_model=FeatureList)
def list_features(
    file_id: str,
    geometry_type: str | None = Query(None, description="Filter, e.g. Polygon"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Features with geometry (GeoJSON, in the file's own CRS) and attributes."""
    record = _get_file_or_404(db, file_id)
    q = select(Feature).where(Feature.file_id == file_id)
    if geometry_type:
        q = q.where(Feature.geometry_type == geometry_type)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Feature.feature_index).limit(limit).offset(offset)).all()
    return FeatureList(
        file_id=file_id,
        crs=record.crs,
        total=total,
        limit=limit,
        offset=offset,
        results=[
            FeatureOut(
                feature_id=f.feature_index,
                geometry_type=f.geometry_type,
                geometry=f.geometry,
                crs=record.crs,
                properties=f.properties or {},
            )
            for f in rows
        ],
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementList)
def get_measurements(
    file_id: str,
    geometry_type: str | None = Query(None, description="Filter, e.g. Polygon"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Per-feature area / length (computed in a projected CRS) plus file-level totals."""
    record = _get_file_or_404(db, file_id)
    if record.status != FileStatus.COMPLETED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"File status is {record.status}; measurements are only available when COMPLETED",
        )

    base = select(Feature).where(Feature.file_id == file_id)
    if geometry_type:
        base = base.where(Feature.geometry_type == geometry_type)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    sub = base.subquery()
    total_area, total_length = db.execute(
        select(func.coalesce(func.sum(sub.c.area_sq_m), 0.0), func.coalesce(func.sum(sub.c.length_m), 0.0))
    ).one()
    status_counts = dict(
        db.execute(select(sub.c.measurement_status, func.count()).group_by(sub.c.measurement_status)).all()
    )

    rows = db.scalars(base.order_by(Feature.feature_index).limit(limit).offset(offset)).all()
    return MeasurementList(
        file_id=file_id,
        crs=record.crs,
        summary=MeasurementSummary(
            total_area_sq_m=total_area, total_length_m=total_length, status_counts=status_counts
        ),
        total=total,
        limit=limit,
        offset=offset,
        results=[
            MeasurementOut(
                feature_id=f.feature_index,
                geometry_type=f.geometry_type,
                status=f.measurement_status,
                measurement_crs=f.measurement_crs,
                area_sq_m=f.area_sq_m,
                area_hectares=f.area_sq_m / 10_000 if f.area_sq_m is not None else None,
                perimeter_m=f.perimeter_m,
                length_m=f.length_m,
                is_valid=f.is_valid,
                note=f.measurement_note,
            )
            for f in rows
        ],
    )
