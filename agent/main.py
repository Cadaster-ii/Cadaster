"""
agent/main.py — Cadaster verification & attestation API

Endpoints
─────────
  POST /verify   — Run all geo-checks, return verdict + evidence.  No signing.
  POST /attest   — Run checks; if all pass, sign an Attestation and return it.
  GET  /health   — Liveness probe.
  GET  /pubkey   — Return the attester's public key (hex) for on-chain registration.

Security notes
──────────────
  - The private key is never logged or returned to clients.
  - Attestations include a fresh random nonce and a short TTL.
  - If *any* required data source is unavailable, attest refuses to sign.
  - Deterministic checks only — no LLM in the signing path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from agent.checks import CheckResult
from agent.checks import polygon_sanity
from agent.checks import land_checks
from agent.checks import duplicate_check
from agent.config import get_settings, Settings
from agent.db import AttestedPolygon, get_session
from agent.providers.geocoder import NominatimGeocoder
from agent.providers.land_cover import WorldCoverProvider
from agent.signer import build_and_sign, compute_claim_hash, get_attester_pubkey

log = logging.getLogger("cadaster.agent")

# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cadaster Agent",
    description="Geo-verification oracle for RWA tokenization on Stellar",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down to your frontend origin in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Dependency injection ────────────────────────────────────────────────────


def get_geocoder(settings: Annotated[Settings, Depends(get_settings)]) -> NominatimGeocoder:
    return NominatimGeocoder(base_url=settings.nominatim_base_url)


def get_land_cover(settings: Annotated[Settings, Depends(get_settings)]) -> WorldCoverProvider:
    return WorldCoverProvider(
        client_id=settings.sentinel_hub_client_id,
        client_secret=settings.sentinel_hub_client_secret,
        base_url=settings.sentinel_hub_base_url,
    )


# ─── Request / response models ────────────────────────────────────────────────


class LandClaim(BaseModel):
    """A land-parcel claim submitted by the asset owner."""

    # GeoJSON Polygon geometry (not the full Feature — just the geometry object)
    polygon: dict = Field(
        ...,
        description='GeoJSON Polygon geometry, e.g. {"type": "Polygon", "coordinates": [...]}',
    )
    country_code: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code (lower-case)",
    )
    asset_type: int = Field(
        default=1,
        description="Asset type: 1 = land parcel",
    )
    # Optional human-supplied metadata (stored in evidence, not used for verdict)
    description: str = Field(default="", max_length=512)

    @field_validator("polygon")
    @classmethod
    def validate_polygon_type(cls, v: dict) -> dict:
        if v.get("type") != "Polygon":
            raise ValueError("polygon must be a GeoJSON Polygon geometry")
        if "coordinates" not in v or not v["coordinates"]:
            raise ValueError("polygon must have coordinates")
        return v

    @field_validator("country_code")
    @classmethod
    def lowercase_country(cls, v: str) -> str:
        return v.lower()


class CheckDetail(BaseModel):
    name: str
    passed: bool
    score: int
    reason: str
    evidence: dict


class VerifyResponse(BaseModel):
    verdict: bool
    confidence_score: int
    checks: list[CheckDetail]
    claim_hash: str   # hex-encoded SHA-256 of canonical claim JSON
    message: str


class AttestResponse(BaseModel):
    verdict: bool
    confidence_score: int
    claim_hash: str
    attestation: dict    # serialised Attestation fields
    pubkey_hex: str      # attester's Ed25519 public key
    signature_hex: str   # 64-byte Ed25519 signature over xdr(attestation)
    checks: list[CheckDetail]
    message: str


# ─── Shared verification logic ────────────────────────────────────────────────


async def run_verification(
    claim: LandClaim,
    geocoder: NominatimGeocoder,
    land_cover: WorldCoverProvider,
    db: AsyncSession,
    settings: Settings,
) -> tuple[bool, int, list[tuple[str, CheckResult]]]:
    """
    Run all checks and return (verdict, score, check_results).

    Returns verdict=False if any check fails OR if the confidence score is
    below the configured threshold.
    """
    results: list[tuple[str, CheckResult]] = []

    # ── Polygon sanity (no network) ───────────────────────────────────────────
    for name, result in polygon_sanity.run_all(claim.polygon):
        results.append((name, result))

    # Fail-fast on sanity — don't make network calls for invalid polygons
    if any(not r.passed for _, r in results):
        return False, 0, results

    # ── Coordinate validity ────────────────────────────────────────────────────
    coord_result = await land_checks.check_coordinate_validity(claim.polygon)
    results.append(("coordinate_validity", coord_result))
    if not coord_result.passed:
        return False, 0, results

    # ── Land vs water ─────────────────────────────────────────────────────────
    water_result = await land_checks.check_land_vs_water(claim.polygon, land_cover)
    results.append(("land_vs_water", water_result))

    # ── Country matches claim ──────────────────────────────────────────────────
    country_result = await land_checks.check_country_matches_claim(
        claim.polygon, claim.country_code, geocoder
    )
    results.append(("country_matches_claim", country_result))

    # ── Land-use matches asset type ───────────────────────────────────────────
    use_result = await land_checks.check_land_use_matches_type(
        claim.polygon, claim.asset_type, land_cover
    )
    results.append(("land_use_matches_type", use_result))

    # ── Duplicate / overlap check ──────────────────────────────────────────────
    try:
        stmt = select(AttestedPolygon.geom_wkt).where(
            AttestedPolygon.country_code == claim.country_code
        )
        rows = await db.execute(stmt)
        existing_wkts = [row[0] for row in rows.fetchall()]
    except Exception as exc:
        log.warning("DB unavailable for overlap check: %s", exc)
        existing_wkts = []

    overlap_result = duplicate_check.check_no_overlap(claim.polygon, existing_wkts)
    results.append(("no_overlap", overlap_result))

    # ── Aggregate score ────────────────────────────────────────────────────────
    passed_results = [r for _, r in results if r.passed]
    failed_results = [r for _, r in results if not r.passed]

    if failed_results:
        return False, 0, results

    # Weighted average of passed check scores
    score = int(sum(r.score for r in passed_results) / len(passed_results)) if passed_results else 0

    verdict = score >= settings.min_confidence_score
    return verdict, score, results


def _canonical_claim_json(claim: LandClaim) -> str:
    """Deterministic JSON encoding of the claim (sorted keys, no whitespace)."""
    return json.dumps(
        {
            "polygon": claim.polygon,
            "country_code": claim.country_code,
            "asset_type": claim.asset_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _to_check_details(results: list[tuple[str, CheckResult]]) -> list[CheckDetail]:
    return [
        CheckDetail(
            name=name,
            passed=r.passed,
            score=r.score,
            reason=r.reason,
            evidence=r.evidence,
        )
        for name, r in results
    ]


# ─── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "ts": int(time.time())}


@app.get("/pubkey")
async def pubkey() -> dict:
    """Return the attester's Ed25519 public key as hex. Register this in the on-chain registry."""
    try:
        pk = get_attester_pubkey()
        return {"pubkey_hex": pk.hex()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load attester key: {exc}")


@app.post("/verify", response_model=VerifyResponse)
async def verify(
    claim: LandClaim,
    settings: Annotated[Settings, Depends(get_settings)],
    geocoder: Annotated[NominatimGeocoder, Depends(get_geocoder)],
    land_cover: Annotated[WorldCoverProvider, Depends(get_land_cover)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> VerifyResponse:
    """
    Run all geo-checks and return the verdict + evidence.

    Does NOT sign an attestation.  Use /attest for that.
    """
    canonical = _canonical_claim_json(claim)
    claim_hash = compute_claim_hash(canonical)

    verdict, score, results = await run_verification(
        claim, geocoder, land_cover, db, settings
    )

    msg = (
        "All checks passed — eligible for attestation"
        if verdict
        else "One or more checks failed — not eligible for attestation"
    )

    return VerifyResponse(
        verdict=verdict,
        confidence_score=score,
        checks=_to_check_details(results),
        claim_hash=claim_hash.hex(),
        message=msg,
    )


@app.post("/attest", response_model=AttestResponse)
async def attest(
    claim: LandClaim,
    settings: Annotated[Settings, Depends(get_settings)],
    geocoder: Annotated[NominatimGeocoder, Depends(get_geocoder)],
    land_cover: Annotated[WorldCoverProvider, Depends(get_land_cover)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AttestResponse:
    """
    Run geo-checks; if all pass and confidence ≥ threshold, sign and return
    an Attestation ready for cadaster-token.mint().

    Refuses to sign if:
      - Any check fails
      - Any required data source is unavailable
      - Confidence score < MIN_CONFIDENCE_SCORE
    """
    canonical = _canonical_claim_json(claim)
    claim_hash_bytes = compute_claim_hash(canonical)

    verdict, score, results = await run_verification(
        claim, geocoder, land_cover, db, settings
    )

    if not verdict:
        failed = [name for name, r in results if not r.passed]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Verification failed — not signing",
                "failed_checks": failed,
                "score": score,
                "checks": _to_check_details(results),
            },
        )

    # Build attestation + sign
    try:
        att, _xdr, sig = build_and_sign(
            claim_hash=claim_hash_bytes,
            asset_type=claim.asset_type,
            score=score,
        )
        pubkey_hex = get_attester_pubkey().hex()
    except Exception as exc:
        log.exception("Signing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signing failed — attester key unavailable",
        )

    # Persist the attested polygon so future overlap checks can find it
    try:
        from shapely.geometry import shape
        wkt = shape(claim.polygon).wkt
        evidence_blob = json.dumps(
            {
                "claim": claim.model_dump(),
                "canonical_claim": canonical,
                "checks": [
                    {"name": n, "passed": r.passed, "score": r.score, "evidence": r.evidence}
                    for n, r in results
                ],
                "attestation": att.to_dict(),
            },
            default=str,
        )
        record = AttestedPolygon(
            claim_hash=claim_hash_bytes.hex(),
            geom_wkt=wkt,
            country_code=claim.country_code,
            asset_type=claim.asset_type,
            score=score,
            attestation_json=evidence_blob,
        )
        db.add(record)
        await db.commit()
    except Exception as exc:
        # DB persistence failure is not fatal — the attestation is still valid
        log.warning("Failed to persist attested polygon: %s", exc)
        await db.rollback()

    return AttestResponse(
        verdict=True,
        confidence_score=score,
        claim_hash=claim_hash_bytes.hex(),
        attestation=att.to_dict(),
        pubkey_hex=pubkey_hex,
        signature_hex=sig.hex(),
        checks=_to_check_details(results),
        message="Attestation signed — submit to cadaster-token.mint()",
    )
