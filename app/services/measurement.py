"""Area / length computation.

Strategy (per feature):
  1. transform the geometry from its source CRS to WGS84 lon/lat,
  2. pick the UTM zone containing the centre of the geometry's bounding box,
  3. transform to that UTM zone (metres) and measure there.

Measuring in a per-feature UTM zone keeps distortion tiny (<0.1% inside the zone)
and makes results independent of whatever CRS the file happened to use
(including Web Mercator, which badly inflates areas away from the equator).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pyproj import CRS
from shapely import force_2d
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app.models import MeasurementStatus
from app.services.crs import WGS84, crs_label, get_transformer, utm_crs_for

POLYGONAL = {"Polygon", "MultiPolygon"}
LINEAR = {"LineString", "LinearRing", "MultiLineString"}
POINTLIKE = {"Point", "MultiPoint"}


@dataclass
class Measurement:
    status: MeasurementStatus
    measurement_crs: str | None = None
    area_sq_m: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    is_valid: bool | None = None
    note: str | None = None


def measure_geometry(geom: BaseGeometry | None, source_crs: CRS) -> Measurement:
    """Measure one geometry. Never raises: problems are reported via ``status``."""
    if geom is None or geom.is_empty:
        return Measurement(MeasurementStatus.UNSUPPORTED, note="Empty or missing geometry")

    gtype = geom.geom_type
    if gtype in POINTLIKE:
        return Measurement(MeasurementStatus.NOT_REQUIRED, note="No measurement defined for points")
    if gtype not in POLYGONAL | LINEAR:
        return Measurement(
            MeasurementStatus.UNSUPPORTED,
            note=f"Measurement is not supported for geometry type '{gtype}'",
        )

    try:
        geom = force_2d(geom)
        lonlat = transform(get_transformer(source_crs, WGS84).transform, geom)
        minx, miny, maxx, maxy = lonlat.bounds
        if not all(map(math.isfinite, (minx, miny, maxx, maxy))) or not (
            -180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90
        ):
            return Measurement(
                MeasurementStatus.ERROR,
                note="Coordinates fall outside valid lon/lat ranges after transformation "
                "(check the file's CRS)",
            )

        utm = utm_crs_for((minx + maxx) / 2, (miny + maxy) / 2)
        projected = transform(get_transformer(WGS84, utm).transform, lonlat)

        notes = []
        if maxx - minx > 6:
            notes.append(
                "Geometry spans more than one UTM zone; result is approximate"
            )
        valid = bool(geom.is_valid)
        if not valid:
            notes.append("Source geometry is invalid (e.g. self-intersection); result may be unreliable")

        result = Measurement(
            MeasurementStatus.OK,
            measurement_crs=crs_label(utm),
            is_valid=valid,
            note="; ".join(notes) or None,
        )
        if gtype in POLYGONAL:
            result.area_sq_m = float(projected.area)
            result.perimeter_m = float(projected.length)
        else:
            result.length_m = float(projected.length)
        return result
    except Exception as exc:  # one bad feature must not sink the file
        return Measurement(MeasurementStatus.ERROR, note=f"Measurement failed: {exc}")
