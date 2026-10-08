"""
agent/checks/land_checks.py

Geo-verification checks specific to land parcels.

Checks
──────
  1. coordinate_validity   — centroid is on land (not Antarctica, not null island)
  2. land_vs_water         — WorldCover dominant class is not "Permanent water bodies"
  3. country_matches_claim — reverse-geocoded country matches the claim's country_code
  4. land_use_matches_type — WorldCover class is consistent with the claimed asset_type
                             (asset_type=1: agricultural/natural land)

Each check is async so providers can make network calls.
"""

from __future__ import annotations

from shapely.geometry import shape

from agent.checks import CheckResult
from agent.providers.geocoder import GeocoderProvider
from agent.providers.land_cover import LandCoverProvider, WORLDCOVER_LABELS

# ── WorldCover classes that are plausibly "land parcel" (asset_type=1) ────────
# Excludes: 80 (water), 70 (ice), 95 (mangrove — too specialist)
LAND_PARCEL_VALID_CLASSES = {10, 20, 30, 40, 50, 60, 90, 100}


async def check_land_vs_water(
    geojson_polygon: dict,
    land_cover: LandCoverProvider,
) -> CheckResult:
    """The polygon must not be predominantly water."""
    result = await land_cover.classify(geojson_polygon)

    if not result.available:
        return CheckResult(
            passed=False,
            score=0,
            reason="Land-cover data unavailable — refusing to attest",
            evidence=result.evidence,
        )

    if result.is_water:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Polygon is predominantly water ({result.dominant_label})",
            evidence={
                "dominant_class": result.dominant_class,
                "dominant_label": result.dominant_label,
                "class_fractions": result.class_fractions,
            },
        )

    # Score: penalise high water fraction even if not dominant
    water_fraction = result.class_fractions.get(80, 0.0)
    score = max(50, int(100 - water_fraction * 100))

    return CheckResult(
        passed=True,
        score=score,
        evidence={
            "dominant_class": result.dominant_class,
            "dominant_label": result.dominant_label,
            "water_fraction": water_fraction,
            "class_fractions": result.class_fractions,
        },
    )


async def check_country_matches_claim(
    geojson_polygon: dict,
    claimed_country_code: str,
    geocoder: GeocoderProvider,
) -> CheckResult:
    """
    The centroid of the polygon, when reverse-geocoded, must match the
    claimed country code.
    """
    poly = shape(geojson_polygon)
    centroid = poly.centroid
    lat, lon = centroid.y, centroid.x

    try:
        geo_result = await geocoder.reverse(lat, lon)
    except Exception as exc:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Geocoder unavailable: {exc}",
            evidence={"error": str(exc)},
        )

    actual = geo_result.country_code.lower()
    claimed = claimed_country_code.lower()

    if actual != claimed:
        return CheckResult(
            passed=False,
            score=0,
            reason=(
                f"Country mismatch: polygon centroid is in '{actual}' "
                f"({geo_result.country}), claim says '{claimed}'"
            ),
            evidence={
                "centroid_lat": lat,
                "centroid_lon": lon,
                "geocoded_country_code": actual,
                "claimed_country_code": claimed,
                "geocoded_country": geo_result.country,
                "geocoder_raw": geo_result.raw,
            },
        )

    return CheckResult(
        passed=True,
        score=95,
        evidence={
            "centroid_lat": lat,
            "centroid_lon": lon,
            "country_code": actual,
            "country": geo_result.country,
            "state": geo_result.state,
        },
    )


async def check_land_use_matches_type(
    geojson_polygon: dict,
    asset_type: int,
    land_cover: LandCoverProvider,
) -> CheckResult:
    """
    The WorldCover dominant class must be consistent with the claimed asset type.

    asset_type=1  → any non-water land class is acceptable (MVP: land parcel)
    """
    result = await land_cover.classify(geojson_polygon)

    if not result.available:
        return CheckResult(
            passed=False,
            score=0,
            reason="Land-cover data unavailable — refusing to attest",
            evidence=result.evidence,
        )

    if asset_type == 1:
        if result.dominant_class not in LAND_PARCEL_VALID_CLASSES and result.dominant_class != 0:
            return CheckResult(
                passed=False,
                score=0,
                reason=(
                    f"Land-use class '{result.dominant_label}' (code {result.dominant_class}) "
                    f"is not consistent with a land parcel (asset_type=1)"
                ),
                evidence={
                    "dominant_class": result.dominant_class,
                    "dominant_label": result.dominant_label,
                },
            )
        return CheckResult(
            passed=True,
            score=85,
            evidence={
                "asset_type": asset_type,
                "dominant_class": result.dominant_class,
                "dominant_label": result.dominant_label,
            },
        )

    # Unknown asset_type — refuse
    return CheckResult(
        passed=False,
        score=0,
        reason=f"Unknown asset_type={asset_type} — only type 1 (land parcel) supported",
        evidence={"asset_type": asset_type},
    )


async def check_coordinate_validity(geojson_polygon: dict) -> CheckResult:
    """
    Centroid must not be in the ocean at (0,0) and must be a real location.

    This is a lightweight sanity check — the geocoder country-match check
    provides stronger coverage.
    """
    poly = shape(geojson_polygon)
    c = poly.centroid
    lat, lon = c.y, c.x

    # Null island guard
    if abs(lat) < 0.1 and abs(lon) < 0.1:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Centroid is at or near null island ({lat:.4f}, {lon:.4f})",
            evidence={"centroid_lat": lat, "centroid_lon": lon},
        )

    # Antarctica guard (land parcels south of -60° are unusual)
    if lat < -60:
        return CheckResult(
            passed=False,
            score=0,
            reason=f"Centroid is in Antarctica or open ocean ({lat:.4f}° S)",
            evidence={"centroid_lat": lat, "centroid_lon": lon},
        )

    return CheckResult(
        passed=True,
        score=100,
        evidence={"centroid_lat": lat, "centroid_lon": lon},
    )
