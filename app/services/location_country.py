"""Offline country check for saved map pins; never trusts browser country labels.

Natural Earth 1:10m with geoBoundaries GEO-ADM0-33476915 for Georgia.
These are generalised maps, not a border survey. A point must be inside
exactly one ISO-coded country. The global 2 km neighbour guard is retained;
unique GE points deeper than 500 m inside its higher-resolution outline can
use that outline instead of a coarse neighbouring-country distance. Overlaps
and ambiguous border/offshore points still require a verified catalogue place.
No network calls, credentials, or new paid services are involved.
"""
from functools import lru_cache
from pathlib import Path
import gzip
import json
import math

_DATA = Path(__file__).resolve().parents[1] / "data" / "country_boundaries_10m.json.gz"
_BORDER_GUARD_M = 2000.0
_GE_INTERIOR_GUARD_M = 500.0
_METRES_PER_DEGREE = 111320.0


def _box(ring):
    return (min(p[0] for p in ring), min(p[1] for p in ring),
            max(p[0] for p in ring), max(p[1] for p in ring))


@lru_cache(maxsize=1)
def _countries():
    with gzip.open(_DATA, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    with gzip.open(_DATA.with_name("georgia_boundary.json.gz"), "rt", encoding="utf-8") as stream:
        georgia = json.load(stream)
    data["countries"] = [feature for feature in data["countries"] if feature["iso"] != "GE"]
    data["countries"] += [{"iso": "GE", "geometry": feature["geometry"]} for feature in georgia["features"]]
    countries = []
    for feature in data["countries"]:
        geometry = feature["geometry"]
        coordinates = geometry["coordinates"]
        polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
        countries.append((feature["iso"], tuple((_box(p[0]), p) for p in polygons if p and p[0])))
    return tuple(countries)


def _within(box, lon, lat, margin_lon=0.0, margin_lat=0.0):
    return box[0]-margin_lon <= lon <= box[2]+margin_lon and box[1]-margin_lat <= lat <= box[3]+margin_lat


def _in_ring(lon, lat, ring):
    inside = False
    previous = ring[-1]
    for point in ring:
        x, y = point
        px, py = previous
        if (y > lat) != (py > lat) and lon < (px-x)*(lat-y)/(py-y)+x:
            inside = not inside
        previous = point
    return inside


def _in_polygon(lon, lat, rings):
    return _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, ring) for ring in rings[1:])


def _near_ring(lon, lat, ring, distance):
    scale_x = _METRES_PER_DEGREE * max(0.001, math.cos(math.radians(lat)))
    scale_y = _METRES_PER_DEGREE
    previous = ring[-1]
    for point in ring:
        ax, ay = (previous[0]-lon)*scale_x, (previous[1]-lat)*scale_y
        bx, by = (point[0]-lon)*scale_x, (point[1]-lat)*scale_y
        dx, dy = bx-ax, by-ay
        length_sq = dx*dx+dy*dy
        t = max(0.0, min(1.0, -(ax*dx+ay*dy)/length_sq)) if length_sq else 0.0
        if (ax+t*dx)**2+(ay+t*dy)**2 <= distance*distance:
            return True
        previous = point
    return False


def _high_resolution_georgia_interior(lat, lon):
    """Use the independently sourced finer GE outline, never browser metadata.

    Natural Earth's coarse RU edge can be hundreds of metres closer than the
    higher-resolution GEO-ADM0-33476915 edge in Dariali. The old global guard
    therefore refused unique GE interior points such as the monastery approach.
    This exception requires more than 500 m of GE interior depth. The caller
    has already rejected every foreign overlap; no coordinate is moved/snapped.
    """
    # A micrometre tolerance keeps an exactly-500 m floating-point boundary
    # guarded rather than accepting it due to arithmetic rounding.
    for iso, polygons in _countries():
        if iso != 'GE':
            continue
        for box, rings in polygons:
            if (_within(box, lon, lat) and _in_polygon(lon, lat, rings)
                    and not any(_near_ring(lon, lat, ring, _GE_INTERIOR_GUARD_M + 1e-6)
                                for ring in rings)):
                return True
    return False


def resolve_country(lat, lon):
    """Return ISO alpha-2 or None when the point cannot be classified safely."""
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    matches = set()
    for iso, polygons in _countries():
        for box, rings in polygons:
            if _within(box, lon, lat) and _in_polygon(lon, lat, rings):
                matches.add(iso)
                break
    if len(matches) != 1:
        return None
    result = next(iter(matches))
    # The unique-match check above always wins over the finer-GE exception.
    if result == "GE" and _high_resolution_georgia_interior(lat, lon):
        return result
    margin_lat = _BORDER_GUARD_M/_METRES_PER_DEGREE
    margin_lon = margin_lat/max(0.001, math.cos(math.radians(lat)))
    for iso, polygons in _countries():
        if iso == result:
            continue
        for box, rings in polygons:
            if _within(box, lon, lat, margin_lon, margin_lat):
                if any(_near_ring(lon, lat, ring, _BORDER_GUARD_M) for ring in rings):
                    return None
    return result
