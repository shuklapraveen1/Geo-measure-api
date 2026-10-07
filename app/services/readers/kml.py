"""KML reader (pure Python, uses defusedxml so XXE / entity bombs are rejected).

KML coordinates are always WGS84 lon/lat (EPSG:4326) per the OGC spec.
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET
from pyproj import CRS
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.errors import FileProcessingError
from app.services.readers.base import ParsedFeature, ParsedFile

GEOMETRY_TAGS = {"Point", "LineString", "LinearRing", "Polygon", "MultiGeometry"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el: Element, name: str) -> Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _children(el: Element, name: str) -> list[Element]:
    return [c for c in el if _local(c.tag) == name]


def _text(el: Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def _parse_coords(el: Element | None) -> list[tuple[float, ...]]:
    raw = _text(_child(el, "coordinates")) if el is not None else None
    if not raw:
        raise ValueError("missing <coordinates>")
    raw = re.sub(r",\s+", ",", raw)  # tolerate "lon, lat, alt"
    coords = []
    for token in raw.split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ValueError(f"bad coordinate tuple '{token}'")
        coords.append(tuple(float(p) for p in parts[:2]))  # drop altitude
    return coords


def _parse_geometry(el: Element) -> BaseGeometry:
    tag = _local(el.tag)
    if tag == "Point":
        coords = _parse_coords(el)
        return Point(coords[0])
    if tag in ("LineString", "LinearRing"):
        return LineString(_parse_coords(el))
    if tag == "Polygon":
        outer = _child(el, "outerBoundaryIs")
        ring = _child(outer, "LinearRing") if outer is not None else None
        if ring is None:
            raise ValueError("Polygon without outerBoundaryIs/LinearRing")
        holes = []
        for inner in _children(el, "innerBoundaryIs"):
            inner_ring = _child(inner, "LinearRing")
            if inner_ring is not None:
                holes.append(_parse_coords(inner_ring))
        return Polygon(_parse_coords(ring), holes)
    if tag == "MultiGeometry":
        parts = [_parse_geometry(c) for c in el if _local(c.tag) in GEOMETRY_TAGS]
        if not parts:
            raise ValueError("empty MultiGeometry")
        kinds = {p.geom_type for p in parts}
        if kinds == {"Point"}:
            return MultiPoint(parts)
        if kinds == {"LineString"}:
            return MultiLineString(parts)
        if kinds == {"Polygon"}:
            return MultiPolygon(parts)
        return GeometryCollection(parts)  # mixed -> reported as unsupported for measurement
    raise ValueError(f"unsupported KML geometry '{tag}'")


def _properties(placemark: Element) -> dict:
    props: dict = {}
    for key in ("name", "description"):
        value = _text(_child(placemark, key))
        if value is not None:
            props[key] = value
    ext = _child(placemark, "ExtendedData")
    if ext is not None:
        for data in _children(ext, "Data"):
            name = data.get("name")
            if name:
                props[name] = _text(_child(data, "value"))
        for schema_data in _children(ext, "SchemaData"):
            for simple in _children(schema_data, "SimpleData"):
                name = simple.get("name")
                if name:
                    props[name] = _text(simple)
    return props


def read_kml(path: Path) -> ParsedFile:
    try:
        root = SafeET.parse(str(path)).getroot()
    except DefusedXmlException as exc:
        raise FileProcessingError(f"KML rejected for security reasons: {exc}") from exc
    except ParseError as exc:
        raise FileProcessingError(f"Malformed KML/XML: {exc}") from exc

    features: list[ParsedFeature] = []
    for el in root.iter():
        if _local(el.tag) != "Placemark":
            continue
        idx = len(features)
        props = _properties(el)
        geom_el = next((c for c in el if _local(c.tag) in GEOMETRY_TAGS), None)
        if geom_el is None:
            features.append(ParsedFeature(idx, None, props, error="Placemark has no supported geometry"))
            continue
        try:
            features.append(ParsedFeature(idx, _parse_geometry(geom_el), props))
        except Exception as exc:  # bad coordinates etc.: keep the feature, flag it
            features.append(ParsedFeature(idx, None, props, error=f"Could not parse geometry: {exc}"))

    if not features:
        raise FileProcessingError("No <Placemark> features found in KML")
    return ParsedFile(crs=CRS.from_epsg(4326), features=features)
