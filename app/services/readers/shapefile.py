"""Zipped Shapefile reader (pyshp). Extraction is hardened against zip-slip / zip-bombs."""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import shapefile  # pyshp
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely import force_2d
from shapely.geometry import shape as shapely_shape

from app.config import Settings
from app.errors import FileProcessingError
from app.services.readers.base import ParsedFeature, ParsedFile, json_safe

WANTED = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


def _extract(zip_path: Path, dest: Path, settings: Settings) -> Path:
    if not zipfile.is_zipfile(zip_path):
        raise FileProcessingError("File is not a valid ZIP archive")
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > settings.max_zip_members:
            raise FileProcessingError("ZIP contains too many files")
        if sum(i.file_size for i in infos) > settings.max_unzipped_bytes:
            raise FileProcessingError("ZIP content is too large when uncompressed")

        shp_names = []
        for info in infos:
            name = Path(info.filename)
            # skip macOS metadata / hidden files; flatten paths (defeats ../ traversal)
            if "__MACOSX" in name.parts or name.name.startswith("."):
                continue
            if name.suffix.lower() not in WANTED:
                continue
            target = dest / name.name
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
            if name.suffix.lower() == ".shp":
                shp_names.append(target)

    if not shp_names:
        raise FileProcessingError("ZIP does not contain a .shp file")
    if len(shp_names) > 1:
        raise FileProcessingError(
            f"ZIP contains {len(shp_names)} shapefiles; upload one shapefile per ZIP"
        )
    return shp_names[0]


def _find_sibling(shp: Path, suffix: str) -> Path | None:
    for p in shp.parent.iterdir():
        if p.stem == shp.stem and p.suffix.lower() == suffix:
            return p
    return None


def read_shapefile_zip(zip_path: Path, settings: Settings) -> ParsedFile:
    with tempfile.TemporaryDirectory(prefix="shp_") as tmp:
        shp = _extract(zip_path, Path(tmp), settings)

        for required in (".shx", ".dbf"):
            if _find_sibling(shp, required) is None:
                raise FileProcessingError(f"Shapefile is missing its {required} component")

        prj = _find_sibling(shp, ".prj")
        if prj is None:
            raise FileProcessingError(
                "Shapefile has no .prj file, so its CRS is unknown. "
                "Measurements can't be computed safely without a CRS."
            )
        try:
            crs = CRS.from_wkt(prj.read_text(errors="replace"))
        except CRSError as exc:
            raise FileProcessingError(f"Could not parse the .prj CRS definition: {exc}") from exc

        cpg = _find_sibling(shp, ".cpg")
        encoding = cpg.read_text().strip() if cpg else "utf-8"

        try:
            reader = shapefile.Reader(
                shp=open(shp, "rb"),
                shx=open(_find_sibling(shp, ".shx"), "rb"),
                dbf=open(_find_sibling(shp, ".dbf"), "rb"),
                encoding=encoding,
                encodingErrors="replace",
            )
        except Exception as exc:
            raise FileProcessingError(f"Could not open shapefile: {exc}") from exc

        features: list[ParsedFeature] = []
        with reader:
            field_names = [f[0] for f in reader.fields[1:]]  # skip DeletionFlag
            for idx, sr in enumerate(reader.iterShapeRecords()):
                props = {k: json_safe(v) for k, v in zip(field_names, list(sr.record))}
                if sr.shape.shapeType == shapefile.NULL:
                    features.append(ParsedFeature(idx, None, props, error="Null shape"))
                    continue
                try:
                    geom = force_2d(shapely_shape(sr.shape.__geo_interface__))
                    features.append(ParsedFeature(idx, geom, props))
                except Exception as exc:
                    features.append(
                        ParsedFeature(idx, None, props, error=f"Could not parse geometry: {exc}")
                    )

        if not features:
            raise FileProcessingError("Shapefile contains no features")
        return ParsedFile(crs=crs, features=features)
