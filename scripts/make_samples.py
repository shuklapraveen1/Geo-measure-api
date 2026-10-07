"""Generate sample KML + zipped Shapefile into ./samples (run from the repo root)."""
import shutil
import tempfile
from pathlib import Path

import shapefile
from pyproj import CRS

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Bengaluru survey</name>
    <Placemark>
      <name>Plot A</name><description>Residential plot</description>
      <ExtendedData><Data name="owner"><value>Asha</value></Data></ExtendedData>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        77.5900,12.9700,0 77.5910,12.9700,0 77.5910,12.9710,0 77.5900,12.9710,0 77.5900,12.9700,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
    <Placemark>
      <name>Plot B (with courtyard)</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          77.60,12.98 77.61,12.98 77.61,12.99 77.60,12.99 77.60,12.98
        </coordinates></LinearRing></outerBoundaryIs>
        <innerBoundaryIs><LinearRing><coordinates>
          77.603,12.983 77.607,12.983 77.607,12.987 77.603,12.987 77.603,12.983
        </coordinates></LinearRing></innerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Access road</name>
      <LineString><coordinates>77.59,12.97 77.595,12.975 77.60,12.98</coordinates></LineString>
    </Placemark>
    <Placemark>
      <name>Benchmark</name>
      <Point><coordinates>77.5905,12.9705,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Mixed (unsupported for measurement)</name>
      <MultiGeometry>
        <Point><coordinates>77.59,12.97</coordinates></Point>
        <LineString><coordinates>77.59,12.97 77.60,12.98</coordinates></LineString>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>
"""
(OUT / "survey.kml").write_text(KML, encoding="utf-8")

# Shapefile in a projected CRS (UTM 43N, EPSG:32643) - Bengaluru
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp) / "parcels"
    w = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
    w.field("name", "C", size=30)
    w.field("zone", "N")
    # clockwise outer rings (Shapefile convention)
    x0, y0 = 780000.0, 1434000.0
    w.poly([[(x0, y0), (x0, y0 + 100), (x0 + 100, y0 + 100), (x0 + 100, y0), (x0, y0)]])
    w.record("Parcel 100x100m", 1)
    w.poly([[(x0 + 200, y0), (x0 + 200, y0 + 50), (x0 + 400, y0 + 50), (x0 + 400, y0), (x0 + 200, y0)]])
    w.record("Parcel 200x50m", 2)
    w.close()
    Path(f"{base}.prj").write_text(CRS.from_epsg(32643).to_wkt(version="WKT1_ESRI"))
    shutil.make_archive(str(OUT / "parcels_utm43n"), "zip", tmp)
print("Samples written to", OUT)
