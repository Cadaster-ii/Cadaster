"""
agent/checks/polygon_sanity.py

Geometric sanity checks on the submitted GeoJSON polygon.

Checks performed
─────────────────
  1. valid_coordinates  — all lat/lon pairs are within [-90,90] / [-180,180]
  2. polygon_closed     — first and last coordinate are identical
  3. non_self_intersecting — Shapely validity check (no figure-8 rings)
  4. plausible_area      — area is between min_polygon_area_m2 and max_polygon_area_km2

All checks are pure-Python (no network required).
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import shape, Polygon as ShapelyPolygon
from shapely.validation import explain_validity

from agent.checks import CheckResult
from agent.config import get_settings


def _polygon_area_m2(geojson_polygon: dict) -> float:
    """
    Approximate geodetic area of a GeoJSON polygon in square metres.

    Uses the spherical excess formula (accurate to ~0.3% for parcels < 100 km).
    For production, replace with pyproj.Geod.geometry_area_perimeter.
    """
    try:
        from pyproj import Geod
        geod = Geod(ellps="WGS84")
        poly = shape(geojson_polygon)
        area, _ = geod.geometry_area_perimeter(poly)
        return abs(area)
    except Exception:
        # Fallback: flat-earth approximation using the centroid latitude
        coords = geojson_polygon["coordinates"][0]
        lats = [c[1] for c in coords]
        lat_rad = math.radians(sum(lats) / len(lats))
        # 1 degree latitude ≈ 111,320 m; 1 degree longitude ≈ 111,320 * cos(lat)
        deg_m_lat = 111_320.0
        deg_m_lon = 111_320.0 * math.cos(lat_rad)

        n = len(coords)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            x_i = coords[i][0] * deg_m_lon
            y_i = coords[i][1] * deg_m_lat
            x_j = coords[j][0] * deg_m_lon
            y_j = coords[j][1] * deg_m_lat
            area += x_i * y_j - x_j * y_i
        return abs(area) / 2.0


def check_valid_coordinates(geojson_polygon: dict) -> CheckResult:
    """All coordinates must be within the valid WGS-84 range."""
    coords = geojson_polygon.get("coordinates", [[]])
    if not coords or not coords[0]:
        return CheckResult(
            passed=False,
            score=0,
            reason="No coordinates found in polygon",
            evidence={"error": "empty_coordinates"},
        )

    invalid = []
    for ring in coords:
        for lon, lat, *_ in ring:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                invalid.append((lon, lat))

    if invalid:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Out-of-range coordinates: {invalid[:3]}",
            evidence={"invalid_coords": invalid[:10]},
        )

    return CheckResult(passed=True, score=100, evidence={"total_coords": len(coords[0])})


def check_polygon_closed(geojson_polygon: dict) -> CheckResult:
    """GeoJSON requires the outer ring to be closed (first == last point)."""
    coords = geojson_polygon.get("coordinates", [[]])
    if not coords or len(coords[0]) < 4:
        return CheckResult(
            passed=False,
            score=0,
            reason="Polygon must have at least 4 positions (3 + closing)",
            evidence={"n_coords": len(coords[0]) if coords else 0},
        )

    first = coords[0][0]
    last = coords[0][-1]
    if first != last:
        return CheckResult(
            passed=False,
            score=0,
            reason="Polygon ring is not closed (first ≠ last coordinate)",
            evidence={"first": first, "last": last},
        )

    return CheckResult(passed=True, score=100, evidence={"n_coords": len(coords[0])})


def check_non_self_intersecting(geojson_polygon: dict) -> CheckResult:
    """Polygon must not self-intersect (Shapely validity check)."""
    try:
        poly: ShapelyPolygon = shape(geojson_polygon)
    except Exception as exc:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Failed to parse polygon: {exc}",
            evidence={"error": str(exc)},
        )

    if not poly.is_valid:
        reason = explain_validity(poly)
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Polygon is not valid: {reason}",
            evidence={"shapely_reason": reason},
        )

    return CheckResult(passed=True, score=100, evidence={"is_valid": True})


def check_plausible_area(geojson_polygon: dict) -> CheckResult:
    """Area must be within configured min/max bounds."""
    settings = get_settings()
    try:
        area_m2 = _polygon_area_m2(geojson_polygon)
    except Exception as exc:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Area computation failed: {exc}",
            evidence={"error": str(exc)},
        )

    area_km2 = area_m2 / 1_000_000.0

    if area_m2 < settings.min_polygon_area_m2:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Polygon too small: {area_m2:.2f} m² (min {settings.min_polygon_area_m2} m²)",
            evidence={"area_m2": area_m2, "limit_m2": settings.min_polygon_area_m2},
        )

    if area_km2 > settings.max_polygon_area_km2:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Polygon too large: {area_km2:.1f} km² (max {settings.max_polygon_area_km2} km²)",
            evidence={"area_km2": area_km2, "limit_km2": settings.max_polygon_area_km2},
        )

    # Score scales linearly between 1 m² (score 60) and reasonable size
    score = min(100, max(60, int(100 - max(0.0, (area_km2 / settings.max_polygon_area_km2)) * 40)))
    return CheckResult(
        passed=True,
        score=score,
        evidence={"area_m2": area_m2, "area_km2": area_km2},
    )


def run_all(geojson_polygon: dict) -> list[tuple[str, CheckResult]]:
    """Run all polygon sanity checks, returning (name, result) pairs."""
    return [
        ("valid_coordinates", check_valid_coordinates(geojson_polygon)),
        ("polygon_closed", check_polygon_closed(geojson_polygon)),
        ("non_self_intersecting", check_non_self_intersecting(geojson_polygon)),
        ("plausible_area", check_plausible_area(geojson_polygon)),
    ]
