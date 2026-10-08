"""
agent/config.py — Runtime configuration via environment variables.

Load from .env for local dev; inject as real env vars in production / CI.
Never commit actual values — see .env.example at the repo root.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Signing key ─────────────────────────────────────────────────────────
    # Hex-encoded 32-byte Ed25519 private key seed.
    # In production, inject this from a secrets manager / KMS.
    attester_private_key_hex: str

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cadaster"

    # ── Geo-check thresholds ──────────────────────────────────────────────────
    # Minimum confidence score (0-100) required to sign an attestation.
    min_confidence_score: int = 70

    # Maximum polygon area in km² before we reject as implausible.
    max_polygon_area_km2: float = 10_000.0

    # Minimum polygon area in m² (rejects sub-metre polygons).
    min_polygon_area_m2: float = 1.0

    # Attestation validity window in seconds (default: 1 hour).
    attestation_ttl_seconds: int = 3600

    # ── External APIs ─────────────────────────────────────────────────────────
    # OSM Nominatim — default public instance; replace with self-hosted for prod.
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"

    # Sentinel Hub OAuth credentials (free tier for Sentinel-2 / WorldCover).
    sentinel_hub_client_id: str = ""
    sentinel_hub_client_secret: str = ""
    sentinel_hub_base_url: str = "https://services.sentinel-hub.com"

    # ── Stellar ───────────────────────────────────────────────────────────────
    stellar_network: str = "testnet"
    registry_contract_id: str = ""
    verifier_contract_id: str = ""
    token_contract_id: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
