import io
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest
import shapefile
from fastapi.testclient import TestClient
from pyproj import CRS

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app) as c:
        yield c


def kml_doc(*placemarks: str) -> bytes:
    body = "".join(placemarks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>'
    ).encode()


def placemark(name: str, geometry: str) -> str:
    return f"<Placemark><name>{name}</name>{geometry}</Placemark>"


def make_shapefile_zip(
    rings=None, lines=None, crs: CRS | None = CRS.from_epsg(32643), include_prj=True, nested=False
) -> bytes:
    """Build an in-memory zipped shapefile (polygons or polylines)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "data"
        if rings is not None:
            w = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
            w.field("name", "C")
            for i, ring in enumerate(rings):
                w.poly([ring])
                w.record(f"poly{i}")
        else:
            w = shapefile.Writer(str(base), shapeType=shapefile.POLYLINE)
            w.field("name", "C")
            for i, line in enumerate(lines):
                w.line([line])
                w.record(f"line{i}")
        w.close()
        if include_prj and crs is not None:
            Path(f"{base}.prj").write_text(crs.to_wkt(version="WKT1_ESRI"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for p in sorted(Path(tmp).iterdir()):
                zf.write(p, f"sub/dir/{p.name}" if nested else p.name)
        return buf.getvalue()
