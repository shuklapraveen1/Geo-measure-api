# Geospatial File Measurement API

A FastAPI backend that accepts a **KML** file or a **zipped Shapefile**, extracts every feature
(ID, geometry type, geometry, CRS, attributes) and returns **area** (polygons) and **length**
(lines), computed in a projected CRS, never in raw degrees.

```
POST /api/files/                      upload + process
GET  /api/files/{id}/                 file info
GET  /api/files/{id}/measurements/    per-feature measurements + totals
GET  /api/files/{id}/features/        geometry + attributes   (extra)
GET  /api/files/                      list uploads            (extra)
DELETE /api/files/{id}/               delete upload           (extra)
```

Interactive docs (Swagger UI) are served at `/docs` once the app is running.

---

## Setup

Requires Python 3.10+. All dependencies are pure `pip` wheels, so no system GDAL is needed.

```bash
git clone https://github.com/shuklapraveen1/Geo-measure-api.git && cd geo-measure-api
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload                          # http://127.0.0.1:8000/docs
pytest -q                                              # run the test-suite (31 tests)
```

Try it with the bundled samples:

```bash
curl -F "file=@samples/survey.kml"          http://127.0.0.1:8000/api/files/
curl -F "file=@samples/parcels_utm43n.zip"  http://127.0.0.1:8000/api/files/
```

Docker:

```bash
docker build -t geo-measure-api .
docker run -p 8000:8000 -v geo_data:/data geo-measure-api
```

Configuration (environment variables, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `GEO_DATA_DIR` | `./data` | Where the SQLite DB and uploaded files live |
| `GEO_DATABASE_URL` | sqlite in `GEO_DATA_DIR` | Any SQLAlchemy URL (e.g. Postgres) |
| `GEO_MAX_UPLOAD_MB` | `50` | Max upload size |
| `GEO_MAX_UNZIPPED_MB` | `500` | Zip-bomb guard |
| `GEO_MAX_ZIP_MEMBERS` | `100` | Max files in a ZIP |

---

## API

### `POST /api/files/`: upload

`multipart/form-data` with a `file` field: a `.kml`, or a `.zip` containing one Shapefile
(`.shp`, `.shx`, `.dbf` and **`.prj`**).

```bash
curl -F "file=@samples/survey.kml" http://127.0.0.1:8000/api/files/
```

`201 Created`
```json
{
  "id": "5908946ba5064de5b7137af29f46e96e",
  "filename": "survey.kml",
  "file_type": "kml",
  "feature_count": 5,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error_message": null,
  "geometry_type_counts": {"GeometryCollection": 1, "LineString": 1, "Point": 1, "Polygon": 2},
  "created_at": "2026-10-07T06:21:57.679819Z"
}
```

| Code | When |
|---|---|
| 201 | processed |
| 400 | wrong extension (e.g. `.geojson`, bare `.shp`) or empty file |
| 413 | larger than `GEO_MAX_UPLOAD_MB` |
| 422 | file accepted but unusable (malformed XML, corrupt ZIP, no `.shp`, missing `.prj`, no features). Body: `{"detail": "...", "file": {... "status": "FAILED"}}` |

### `GET /api/files/{id}/`: file info
Returns the same object as the upload response. `404` for unknown ids.

### `GET /api/files/{id}/measurements/`

Query params: `geometry_type` (e.g. `Polygon`), `limit` (default 1000, max 5000), `offset`.
`409` if the file's status is not `COMPLETED`.

```json
{
  "file_id": "5908946ba5064de5b7137af29f46e96e",
  "crs": "EPSG:4326",
  "summary": {
    "total_area_sq_m": 1021407.01,
    "total_length_m": 1550.43,
    "status_counts": {"OK": 3, "NOT_REQUIRED": 1, "UNSUPPORTED": 1}
  },
  "total": 5, "limit": 1000, "offset": 0,
  "results": [
    {
      "feature_id": 0, "geometry_type": "Polygon", "status": "OK",
      "measurement_crs": "EPSG:32643",
      "area_sq_m": 12016.97, "area_hectares": 1.2017, "perimeter_m": 438.51,
      "length_m": null, "is_valid": true, "note": null
    },
    {
      "feature_id": 2, "geometry_type": "LineString", "status": "OK",
      "measurement_crs": "EPSG:32643",
      "area_sq_m": null, "area_hectares": null, "perimeter_m": null,
      "length_m": 1550.43, "is_valid": true, "note": null
    },
    {
      "feature_id": 3, "geometry_type": "Point", "status": "NOT_REQUIRED",
      "measurement_crs": null, "area_sq_m": null, "area_hectares": null,
      "perimeter_m": null, "length_m": null, "is_valid": null,
      "note": "No measurement defined for points"
    },
    {
      "feature_id": 4, "geometry_type": "GeometryCollection", "status": "UNSUPPORTED",
      "note": "Measurement is not supported for geometry type 'GeometryCollection'"
    }
  ]
}
```

Per-feature `status`:

| status | meaning |
|---|---|
| `OK` | area (polygons) or length (lines) computed |
| `NOT_REQUIRED` | Point / MultiPoint |
| `UNSUPPORTED` | e.g. `GeometryCollection`, empty/null geometry |
| `ERROR` | this feature couldn't be parsed or measured (reason in `note`); the rest of the file is unaffected |

`summary` always covers *all* matching features, not just the returned page.

### `GET /api/files/{id}/features/`
Same pagination/filter params. Each feature has `feature_id`, `geometry_type`, `geometry`
(GeoJSON, **in the file's own CRS**), `crs` and `properties`.

### Extras
`GET /api/files/` (paginated list), `DELETE /api/files/{id}/` (removes DB rows and stored file), `GET /health`.

---

## Architecture

```
app/
  main.py               app factory, wiring (engine, session factory, router)
  config.py             env-driven settings
  database.py, models.py  SQLAlchemy 2.0: UploadedFile 1──* Feature
  schemas.py            Pydantic response models
  api/files.py          HTTP layer: validation, streaming upload, queries
  services/
    processing.py       orchestration: parse -> measure -> persist
    readers/kml.py      KML parser (defusedxml + shapely)
    readers/shapefile.py  safe ZIP extraction + pyshp + .prj CRS
    measurement.py      projection + area/length
    crs.py              CRS labels, UTM zone picker
tests/                  31 tests (API behaviour, accuracy vs geodesic, edge cases)
```

The HTTP layer knows nothing about file formats; readers know nothing about HTTP or the database.
Adding a format (GeoJSON, GPKG) means writing one function that returns a `ParsedFile`.

### File-processing flow
1. **Validate**: extension must be `.kml` or `.zip`; body is streamed to disk with a size cap.
2. **Record**: an `UploadedFile` row is committed with status `PROCESSING`.
3. **Read**: a format-specific reader returns `ParsedFile(crs, [ParsedFeature])`.
   - *KML*: parsed with `defusedxml` (blocks XXE / entity bombs). Handles namespaces, folders,
     `Point/LineString/LinearRing/Polygon` (with holes), `MultiGeometry`, `ExtendedData`/`SchemaData`.
     CRS is EPSG:4326 by specification.
   - *Shapefile*: ZIP members are filtered to known extensions and **flattened** (zip-slip safe),
     with member-count and uncompressed-size limits (zip-bomb safe). CRS comes from the `.prj`.
4. **Measure** each feature (below). A feature that fails to parse or measure is kept and flagged;
   it never fails the whole file.
5. **Persist** all features in one transaction and set `COMPLETED` (or `FAILED` + `error_message`).

### Measurement flow
```
geometry (file CRS) ─▶ WGS84 lon/lat ─▶ pick UTM zone from bbox centre ─▶ UTM (metres) ─▶ area / length
```
- Polygon / MultiPolygon: `area_sq_m` (holes subtracted) and `perimeter_m`.
- LineString / LinearRing / MultiLineString: `length_m`.
- Point / MultiPoint: `NOT_REQUIRED`. Everything else: `UNSUPPORTED`. No exceptions leak.
- Z values are dropped; geometry validity is reported in `is_valid` (self-intersecting polygons still get a number, plus a warning note).

### CRS handling
- **Never measure in degrees.** Even for EPSG:4326 input, geometry is reprojected first.
- **Strategy: per-feature UTM.** The zone is derived from the centre of the feature's bounding box
  (`EPSG:326xx` north, `327xx` south; UPS `32661`/`32761` beyond 84°N / 80°S). Distortion inside a
  zone is < 0.1%.
- **Always go through WGS84 first, even for projected input.** Result is independent of the file's
  CRS, so Web Mercator (which inflates areas ~5% at 13°N and far more at high latitudes) can't
  skew results. A test verifies this.
- Input axis order is normalised with `always_xy=True`.
- Sanity check: if transformed coordinates fall outside valid lon/lat (typically a wrong/mislabelled CRS) the feature is flagged `ERROR` instead of returning a garbage number.
- Tests compare results to PROJ's ellipsoidal geodesic area/length (`pyproj.Geod`): within 0.3%.

---

## Design decisions & alternatives

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Typed request/response models, auto OpenAPI docs, small surface area. | Django + DRF: heavier for a 3-endpoint service; would shine with auth/admin. |
| **pyshp + own KML parser + shapely** instead of GeoPandas/Fiona/GDAL | Pure-Python wheels: `pip install` just works (no GDAL), small image, full control over errors and per-feature fault tolerance. | GeoPandas/pyogrio: more formats for free, but heavy install and less control over KML quirks. |
| **UTM per feature** | Accurate, simple, explainable, no extra data. | *Geodesic* (`pyproj.Geod`): accurate everywhere and arguably better for huge features. I kept the projected approach because the task asks for it, and use geodesic as the test oracle. *Equal-area (e.g. EASE-Grid / Albers)*: great for area, poor for length. *Per-file UTM*: fails for files spanning zones. |
| **Synchronous processing** | Typical survey files process in milliseconds to seconds; status is `COMPLETED` by the time the upload returns. | Background worker (Celery/RQ/ARQ) + polling on `status`. The `PROCESSING/COMPLETED/FAILED` model is already in place for it. |
| **SQLite + SQLAlchemy** | Zero-setup local run; swap via `GEO_DATABASE_URL`. | PostGIS: spatial queries/indices, a natural next step. |
| **Geometry stored as GeoJSON in the file's CRS** | Lossless w.r.t. the upload. | Normalising everything to 4326 would hide the original CRS. |
| **Measurements stored as columns** | Totals / filters are SQL aggregates, no recomputation on GET. | Compute on read: always fresh, but slower for big files. |
| **Failed uploads are recorded (HTTP 422 + FAILED row)** | Client gets a reason and an id to query/delete. | Reject without persisting. |
| **Missing `.prj` ⇒ 422** | Guessing a CRS silently produces wrong numbers. | Assume EPSG:4326 / accept a `crs` form field override (listed under future scope). |
| **One shapefile per ZIP** | Unambiguous mapping of upload → file. | Treat each `.shp` as a layer. |

Known limitations: features that straddle several UTM zones are flagged as approximate;
Norway/Svalbard UTM zone exceptions are not special-cased; KMZ, `gx:Track`, and 3D height aren't handled.

---

## Learnings

- Area in degrees is meaningless, and "just use EPSG:3857" is also wrong. Projection choice is an
  accuracy decision, so validating against an independent geodesic calculation was the most useful test.
- Real-world files are messy: namespaces vary, coordinates contain stray spaces/altitudes, shapefiles
  have null shapes and no `.prj`. Making failure **per-feature** rather than per-file keeps the API useful.
- Untrusted uploads need defensive handling: zip-slip, zip-bombs, XML entity expansion, size limits.
- pyshp's ring orientation rules (clockwise = exterior) matter when generating test data.

## Future scope

- Async processing (task queue) with progress reporting and webhooks for large files.
- More formats: GeoJSON, KMZ, GeoPackage; multi-layer shapefile ZIPs.
- Optional `crs` override for `.prj`-less shapefiles; `?units=` (acres, km², miles) on measurements.
- Geodesic mode (`?method=geodesic`) and a cross-check delta against the projected result.
- PostGIS storage + spatial queries (bbox filter, intersects), vector-tile / GeoJSON export in 4326.
- Alembic migrations, auth + per-user quotas, rate limiting, object storage (S3) for uploads.
- Handling of multi-zone features by splitting or using a local equal-area/azimuthal CRS.
- Load tests and streaming parsing for very large files; Prometheus metrics.
