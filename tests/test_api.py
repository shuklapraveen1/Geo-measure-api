import io
import zipfile

import pytest
from pyproj import CRS, Geod

from tests.conftest import kml_doc, make_shapefile_zip, placemark

GEOD = Geod(ellps="WGS84")

SQUARE = "77.59,12.97 77.60,12.97 77.60,12.98 77.59,12.98 77.59,12.97"
POLY = f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{SQUARE}</coordinates></LinearRing></outerBoundaryIs></Polygon>"
LINE = "<LineString><coordinates>77.59,12.97 77.60,12.98</coordinates></LineString>"
POINT = "<Point><coordinates>77.59,12.97,0</coordinates></Point>"


def upload(client, name, content, ctype="application/octet-stream"):
    return client.post("/api/files/", files={"file": (name, content, ctype)})


# ---------------------------------------------------------------- KML
def test_kml_upload_and_measure(client):
    data = kml_doc(placemark("a", POLY), placemark("b", LINE), placemark("c", POINT))
    r = upload(client, "survey.kml", data)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 3
    assert info["crs"] == "EPSG:4326"
    assert info["filename"] == "survey.kml"
    assert info["geometry_type_counts"] == {"Polygon": 1, "LineString": 1, "Point": 1}

    # GET /files/{id}/
    assert client.get(f"/api/files/{info['id']}/").json()["feature_count"] == 3

    m = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_id = {x["feature_id"]: x for x in m["results"]}

    # Polygon area must match the ellipsoidal (geodesic) area within 0.3%
    lons, lats = zip(*[tuple(map(float, p.split(","))) for p in SQUARE.split()])
    geodesic_area, geodesic_perimeter = GEOD.polygon_area_perimeter(lons, lats)
    poly = by_id[0]
    assert poly["status"] == "OK"
    assert poly["measurement_crs"] == "EPSG:32643"
    assert poly["area_sq_m"] == pytest.approx(abs(geodesic_area), rel=3e-3)
    assert poly["perimeter_m"] == pytest.approx(geodesic_perimeter, rel=3e-3)
    assert poly["area_hectares"] == pytest.approx(poly["area_sq_m"] / 10_000)
    # sanity: 0.01 deg x 0.01 deg near 13N is about 1.1 km x 1.08 km, NOT ~1e-4 "degree^2"
    assert 1.0e6 < poly["area_sq_m"] < 1.4e6

    line = by_id[1]
    geodesic_len = GEOD.line_length([77.59, 77.60], [12.97, 12.98])
    assert line["length_m"] == pytest.approx(geodesic_len, rel=3e-3)
    assert line["area_sq_m"] is None

    point = by_id[2]
    assert point["status"] == "NOT_REQUIRED"
    assert point["area_sq_m"] is None and point["length_m"] is None

    assert m["summary"]["status_counts"] == {"OK": 2, "NOT_REQUIRED": 1}
    assert m["summary"]["total_area_sq_m"] == pytest.approx(poly["area_sq_m"])


def test_kml_polygon_with_hole_subtracts_area(client):
    hole = "77.593,12.973 77.597,12.973 77.597,12.977 77.593,12.977 77.593,12.973"
    geom = (
        f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{SQUARE}</coordinates></LinearRing></outerBoundaryIs>"
        f"<innerBoundaryIs><LinearRing><coordinates>{hole}</coordinates></LinearRing></innerBoundaryIs></Polygon>"
    )
    solid = upload(client, "s.kml", kml_doc(placemark("s", POLY))).json()["id"]
    holed = upload(client, "h.kml", kml_doc(placemark("h", geom))).json()["id"]
    a_solid = client.get(f"/api/files/{solid}/measurements/").json()["results"][0]["area_sq_m"]
    a_holed = client.get(f"/api/files/{holed}/measurements/").json()["results"][0]["area_sq_m"]
    assert a_holed == pytest.approx(a_solid * (1 - 0.16), rel=1e-2)  # hole is 40% x 40% of the side


def test_kml_unsupported_and_broken_features_are_graceful(client):
    mixed = (
        "<MultiGeometry><Point><coordinates>77.59,12.97</coordinates></Point>"
        "<LineString><coordinates>77.59,12.97 77.60,12.98</coordinates></LineString></MultiGeometry>"
    )
    broken = "<LineString><coordinates>not,numbers</coordinates></LineString>"
    no_geom = "<name>ignored</name>"
    multi_poly = (
        "<MultiGeometry>"
        f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{SQUARE}</coordinates></LinearRing></outerBoundaryIs></Polygon>"
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>77.61,12.97 77.62,12.97 77.62,12.98 77.61,12.97</coordinates></LinearRing></outerBoundaryIs></Polygon>"
        "</MultiGeometry>"
    )
    data = kml_doc(
        placemark("mixed", mixed), placemark("broken", broken), placemark("nogeom", no_geom),
        placemark("multi", multi_poly), placemark("ok", POLY),
    )
    r = upload(client, "weird.kml", data)
    assert r.status_code == 201
    fid = r.json()["id"]
    res = client.get(f"/api/files/{fid}/measurements/").json()["results"]
    statuses = [x["status"] for x in res]
    assert statuses == ["UNSUPPORTED", "ERROR", "ERROR", "OK", "OK"]
    assert "GeometryCollection" in res[0]["note"]
    assert res[3]["geometry_type"] == "MultiPolygon" and res[3]["area_sq_m"] > res[4]["area_sq_m"]


def test_kml_extended_data_and_properties(client):
    pm = (
        "<Placemark><name>x</name><description>d</description>"
        '<ExtendedData><Data name="owner"><value>Asha</value></Data>'
        '<SchemaData schemaUrl="#s"><SimpleData name="zone">7</SimpleData></SchemaData></ExtendedData>'
        f"{POINT}</Placemark>"
    )
    fid = upload(client, "p.kml", kml_doc(pm)).json()["id"]
    feats = client.get(f"/api/files/{fid}/features/").json()
    f = feats["results"][0]
    assert f["feature_id"] == 0 and f["geometry_type"] == "Point" and f["crs"] == "EPSG:4326"
    assert f["properties"] == {"name": "x", "description": "d", "owner": "Asha", "zone": "7"}
    assert f["geometry"]["type"] == "Point"


def test_kml_malformed_xml_is_422_and_recorded_as_failed(client):
    r = upload(client, "bad.kml", b"<kml><Placemark>")
    assert r.status_code == 422
    body = r.json()
    assert body["file"]["status"] == "FAILED"
    fid = body["file"]["id"]
    assert client.get(f"/api/files/{fid}/").json()["status"] == "FAILED"
    assert client.get(f"/api/files/{fid}/measurements/").status_code == 409


def test_kml_entity_bomb_rejected(client):
    bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>&lol2;</name></Placemark></kml>"""
    r = upload(client, "bomb.kml", bomb)
    assert r.status_code == 422


def test_kml_without_placemarks_is_422(client):
    assert upload(client, "empty.kml", kml_doc("")).status_code == 422


# ---------------------------------------------------------------- Shapefile
def test_shapefile_projected_crs(client):
    x0, y0 = 780000.0, 1434000.0
    ring = [(x0, y0), (x0, y0 + 100), (x0 + 100, y0 + 100), (x0 + 100, y0), (x0, y0)]
    r = upload(client, "parcels.zip", make_shapefile_zip(rings=[ring]))
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["crs"] == "EPSG:32643" and info["feature_count"] == 1
    assert info["file_type"] == "shapefile"
    m = client.get(f"/api/files/{info['id']}/measurements/").json()["results"][0]
    assert m["area_sq_m"] == pytest.approx(10_000, rel=1e-6)
    assert m["perimeter_m"] == pytest.approx(400, rel=1e-6)
    f = client.get(f"/api/files/{info['id']}/features/").json()["results"][0]
    assert f["properties"] == {"name": "poly0"}
    assert f["geometry"]["type"] == "Polygon"


def test_shapefile_geographic_crs_and_nested_zip(client):
    ring = [(77.59, 12.97), (77.59, 12.98), (77.60, 12.98), (77.60, 12.97), (77.59, 12.97)]
    r = upload(client, "geo.zip", make_shapefile_zip(rings=[ring], crs=CRS.from_epsg(4326), nested=True))
    assert r.status_code == 201, r.text
    assert r.json()["crs"] == "EPSG:4326"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["results"][0]
    lons, lats = zip(*ring)
    assert m["area_sq_m"] == pytest.approx(abs(GEOD.polygon_area_perimeter(lons, lats)[0]), rel=3e-3)


def test_shapefile_web_mercator_not_inflated(client):
    """EPSG:3857 areas are inflated ~5% at 12.97N; we must report real ground area."""
    from pyproj import Transformer

    t = Transformer.from_crs(4326, 3857, always_xy=True)
    ring_ll = [(77.59, 12.97), (77.59, 12.98), (77.60, 12.98), (77.60, 12.97), (77.59, 12.97)]
    ring = [t.transform(x, y) for x, y in ring_ll]
    r = upload(client, "merc.zip", make_shapefile_zip(rings=[ring], crs=CRS.from_epsg(3857)))
    assert r.status_code == 201, r.text
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["results"][0]
    lons, lats = zip(*ring_ll)
    assert m["area_sq_m"] == pytest.approx(abs(GEOD.polygon_area_perimeter(lons, lats)[0]), rel=3e-3)


def test_shapefile_polyline_length(client):
    line = [(780000.0, 1434000.0), (780300.0, 1434400.0)]  # 3-4-5 triangle -> 500 m
    r = upload(client, "roads.zip", make_shapefile_zip(lines=[line]))
    assert r.status_code == 201, r.text
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["results"][0]
    assert m["length_m"] == pytest.approx(500, rel=1e-6)


def test_shapefile_missing_prj_rejected(client):
    ring = [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]
    r = upload(client, "noprj.zip", make_shapefile_zip(rings=[ring], include_prj=False))
    assert r.status_code == 422
    assert ".prj" in r.json()["detail"]


def test_zip_without_shp_and_corrupt_zip(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hi")
    assert upload(client, "x.zip", buf.getvalue()).status_code == 422
    assert upload(client, "y.zip", b"definitely not a zip").status_code == 422


def test_zip_slip_member_names_are_neutralised(client, tmp_path):
    ring = [(780000.0, 1434000.0), (780000.0, 1434100.0), (780100.0, 1434100.0), (780100.0, 1434000.0), (780000.0, 1434000.0)]
    src = zipfile.ZipFile(io.BytesIO(make_shapefile_zip(rings=[ring])))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in src.namelist():
            zf.writestr(f"../../evil/{n}", src.read(n))
    r = upload(client, "slip.zip", buf.getvalue())
    assert r.status_code == 201
    assert not (tmp_path / "evil").exists()


# ---------------------------------------------------------------- API behaviour
def test_rejects_wrong_extension(client):
    r = upload(client, "data.geojson", b"{}")
    assert r.status_code == 400
    r = upload(client, "data.shp", b"abc")
    assert r.status_code == 400 and "Zip" in r.json()["detail"]


def test_rejects_empty_file(client):
    assert upload(client, "e.kml", b"").status_code == 400


def test_unknown_id_404(client):
    for path in ("", "measurements/", "features/"):
        assert client.get(f"/api/files/nope/{path}").status_code == 404


def test_list_pagination_filter_and_delete(client):
    data = kml_doc(*[placemark(f"p{i}", POLY) for i in range(5)], placemark("l", LINE))
    fid = upload(client, "many.kml", data).json()["id"]

    m = client.get(f"/api/files/{fid}/measurements/", params={"limit": 2, "offset": 1}).json()
    assert m["total"] == 6 and [x["feature_id"] for x in m["results"]] == [1, 2]
    assert m["summary"]["status_counts"] == {"OK": 6}  # summary covers all rows, not just the page

    m = client.get(f"/api/files/{fid}/measurements/", params={"geometry_type": "LineString"}).json()
    assert m["total"] == 1 and m["results"][0]["length_m"] > 0

    assert client.get("/api/files/").json()["total"] == 1
    assert client.delete(f"/api/files/{fid}/").status_code == 204
    assert client.get(f"/api/files/{fid}/").status_code == 404
    assert client.get("/api/files/").json()["total"] == 0


def test_upload_size_limit(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(data_dir=tmp_path / "d", max_upload_bytes=100))
    with TestClient(app) as c:
        assert upload(c, "big.kml", b"x" * 500).status_code == 413


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
