import pytest
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.models import MeasurementStatus
from app.services.crs import crs_label, utm_crs_for
from app.services.measurement import measure_geometry

WGS84 = CRS.from_epsg(4326)


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [(77.59, 12.97, 32643), (-0.1, 51.5, 32630), (-122.4, 37.8, 32610), (151.2, -33.9, 32756),
     (180.0, 10, 32660), (0, 89, 32661), (0, -85, 32761)],
)
def test_utm_zone_selection(lon, lat, epsg):
    assert crs_label(utm_crs_for(lon, lat)) == f"EPSG:{epsg}"


def test_point_not_required_and_collection_unsupported():
    assert measure_geometry(Point(1, 1), WGS84).status == MeasurementStatus.NOT_REQUIRED
    gc = GeometryCollection([Point(1, 1), LineString([(0, 0), (1, 1)])])
    assert measure_geometry(gc, WGS84).status == MeasurementStatus.UNSUPPORTED
    assert measure_geometry(None, WGS84).status == MeasurementStatus.UNSUPPORTED
    assert measure_geometry(Polygon(), WGS84).status == MeasurementStatus.UNSUPPORTED


def test_out_of_range_degrees_flagged_as_error():
    # looks like "projected" numbers but file claims EPSG:4326
    poly = Polygon([(780000, 1434000), (780100, 1434000), (780100, 1434100), (780000, 1434000)])
    m = measure_geometry(poly, WGS84)
    assert m.status == MeasurementStatus.ERROR


def test_invalid_polygon_flagged():
    bowtie = Polygon([(77.0, 12.0), (77.01, 12.01), (77.01, 12.0), (77.0, 12.01), (77.0, 12.0)])
    m = measure_geometry(bowtie, WGS84)
    assert m.status == MeasurementStatus.OK and m.is_valid is False and "invalid" in m.note


def test_z_coordinates_ignored():
    m = measure_geometry(LineString([(77.0, 12.0, 900), (77.0, 12.01, 100)]), WGS84)
    assert m.status == MeasurementStatus.OK and 1100 < m.length_m < 1120
