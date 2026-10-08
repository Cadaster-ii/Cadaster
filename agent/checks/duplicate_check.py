"""
agent/checks/duplicate_check.py

Check whether the submitted polygon overlaps with any previously attested parcel.

Implementation
──────────────
  - Lightweight path: compare WKT via Shapely (no PostGIS needed for MVP).
  - Production path: use PostGIS ST_Overlaps or ST_Intersects on the
    attested_polygons table for indexed spatial queries.

The check accepts a list of existing WKT polygons (loaded from DB by the
caller) so it remains a pure function testable without a live database.
"""

from __future__ import annotations

from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from agent.checks import CheckResult


def check_no_overlap(
    geojson_polygon: dict,
    existing_wkts: list[str],
    max_overlap_fraction: float = 0.05,
) -> CheckResult:
    """
    Returns passed=True if the polygon does not overlap >5% with any
    previously attested parcel.

    Parameters
    ──────────
    geojson_polygon     — the candidate GeoJSON polygon
    existing_wkts       — WKT strings of previously attested parcels
    max_overlap_fraction — maximum allowed overlap as a fraction of new polygon area
    """
    if not existing_wkts:
        return CheckResult(passed=True, score=100, evidence={"checked_against": 0})

    try:
        new_poly = make_valid(shape(geojson_polygon))
    except Exception as exc:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Failed to parse new polygon: {exc}",
            evidence={"error": str(exc)},
        )

    new_area = new_poly.area
    if new_area == 0:
        return CheckResult(
            passed=False,
            score=0,
            reason="New polygon has zero area",
            evidence={"area": 0},
        )

    overlapping = []
    for i, wkt in enumerate(existing_wkts):
        try:
            from shapely.wkt import loads
            existing = make_valid(loads(wkt))
            if new_poly.intersects(existing):
                intersection = new_poly.intersection(existing)
                overlap_frac = intersection.area / new_area
                if overlap_frac > max_overlap_fraction:
                    overlapping.append(
                        {"index": i, "overlap_fraction": round(overlap_frac, 4)}
                    )
        except Exception:
            continue  # Skip malformed existing polygons

    if overlapping:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Polygon overlaps with {len(overlapping)} existing attested parcel(s)",
            evidence={
                "overlapping": overlapping,
                "max_overlap_fraction": max_overlap_fraction,
            },
        )

    return CheckResult(
        passed=True,
        score=100,
        evidence={"checked_against": len(existing_wkts), "overlapping": []},
    )
