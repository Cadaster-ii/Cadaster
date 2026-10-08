"""
agent/providers/geocoder.py

Reverse-geocoder provider.

Interface
─────────
    GeocoderProvider.reverse(lat, lon) -> GeocoderResult

Free backend
────────────
    NominatimGeocoder — calls OSM Nominatim (free, no API key needed).
    Rate-limit: 1 req/s per the Nominatim usage policy.  For production use a
    self-hosted instance or a paid provider.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


# ─── Interface ────────────────────────────────────────────────────────────────


@dataclass
class GeocoderResult:
    country_code: str   # ISO 3166-1 alpha-2, lower-case (e.g. "us", "fr")
    country: str        # Full country name
    state: str          # State / region (may be empty)
    raw: dict           # Full response for audit / evidence


class GeocoderProvider(ABC):
    @abstractmethod
    async def reverse(self, lat: float, lon: float) -> GeocoderResult:
        """Reverse-geocode a coordinate to an administrative location."""


# ─── OSM Nominatim implementation ─────────────────────────────────────────────


class NominatimGeocoder(GeocoderProvider):
    """
    Calls the public OSM Nominatim API.

    Nominatim Terms of Service require:
      - A descriptive User-Agent header identifying your application.
      - No more than 1 request per second.
      - No bulk geocoding without prior permission.
    """

    def __init__(self, base_url: str = "https://nominatim.openstreetmap.org") -> None:
        self._base_url = base_url.rstrip("/")
        self._last_request: float = 0.0

    async def reverse(self, lat: float, lon: float) -> GeocoderResult:
        # Nominatim rate-limit: 1 req/s
        now = asyncio.get_event_loop().time()
        wait = 1.0 - (now - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)

        url = f"{self._base_url}/reverse"
        params = {
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "addressdetails": 1,
            "accept-language": "en",
        }
        headers = {
            "User-Agent": "Cadaster/0.1 (geo-verification oracle; github.com/cadaster-project/cadaster)"
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = client.build_request("GET", url, params=params, headers=headers)
            response = await client.send(resp)
            response.raise_for_status()
            self._last_request = asyncio.get_event_loop().time()

        data: dict = response.json()

        address = data.get("address", {})
        country_code = address.get("country_code", "").lower()
        country = address.get("country", "")
        state = address.get("state", address.get("region", ""))

        return GeocoderResult(
            country_code=country_code,
            country=country,
            state=state,
            raw=data,
        )
