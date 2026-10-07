"""CRS helpers: labelling and choosing a projected CRS for measurement."""
from __future__ import annotations

from functools import lru_cache

from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)


def crs_label(crs: CRS) -> str:
    """Human friendly identifier, preferring ``EPSG:xxxx``."""
    epsg = crs.to_epsg(min_confidence=70)
    if epsg:
        return f"EPSG:{epsg}"
    auth = crs.to_authority(min_confidence=70)
    if auth:
        return f"{auth[0]}:{auth[1]}"
    return crs.name or "UNKNOWN"


@lru_cache(maxsize=256)
def get_transformer(src: CRS, dst: CRS) -> Transformer:
    # always_xy keeps (x=lon, y=lat) ordering regardless of the CRS axis definition.
    return Transformer.from_crs(src, dst, always_xy=True)


def utm_crs_for(lon: float, lat: float) -> CRS:
    """Pick the UTM zone (WGS84) covering lon/lat; polar stereographic near the poles."""
    if lat > 84:
        return CRS.from_epsg(32661)  # UPS North
    if lat < -80:
        return CRS.from_epsg(32761)  # UPS South
    zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)
