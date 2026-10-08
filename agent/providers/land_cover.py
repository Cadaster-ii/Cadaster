"""
agent/providers/land_cover.py

Land-cover classification provider.

Interface
─────────
    LandCoverProvider.classify(polygon_geojson) -> LandCoverResult

Free backend
────────────
    WorldCoverProvider — queries ESA WorldCover 2021 (10 m global land cover)
    via Sentinel Hub's free Bring-Your-Own-Data tier.

    Requires:
        SENTINEL_HUB_CLIENT_ID and SENTINEL_HUB_CLIENT_SECRET in env.

    If no credentials are configured the provider falls back to a conservative
    "unknown" classification so the pipeline can still run but will refuse to
    attest (unknown class is treated as unavailable data).

WorldCover class codes (v2.0)
─────────────────────────────
    10  Tree cover
    20  Shrubland
    30  Grassland
    40  Cropland           ← land-use type 1 (agricultural land)
    50  Built-up           ← land-use type 2 (urban / infrastructure)
    60  Bare / sparse vegetation
    70  Snow and ice
    80  Permanent water bodies  ← water
    90  Herbaceous wetland
    95  Mangroves
    100 Moss and lichen
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx


# ─── Interface ────────────────────────────────────────────────────────────────


@dataclass
class LandCoverResult:
    dominant_class: int           # WorldCover class code of the dominant pixel
    dominant_label: str           # Human-readable label
    class_fractions: dict[int, float]  # class_code → fraction of polygon (0–1)
    is_water: bool                # True if dominant class is water (code 80)
    available: bool = True        # False when data source was unreachable
    evidence: dict = field(default_factory=dict)


class LandCoverProvider(ABC):
    @abstractmethod
    async def classify(self, geojson_polygon: dict) -> LandCoverResult:
        """Return land-cover statistics for the given GeoJSON polygon."""


# ─── Class label lookup ───────────────────────────────────────────────────────

WORLDCOVER_LABELS: dict[int, str] = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
    0: "Unknown",
}


# ─── Sentinel Hub / WorldCover implementation ──────────────────────────────────


class WorldCoverProvider(LandCoverProvider):
    """
    Uses Sentinel Hub's Statistical API to compute pixel-class histograms
    for ESA WorldCover 2021.

    Free tier: 30,000 processing units / month.  A typical polygon statistical
    query costs <10 PU.

    Docs: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Statistical.html
    """

    # Sentinel Hub collection ID for ESA WorldCover 2021
    WORLDCOVER_COLLECTION = "ESA_WORLDCOVER_10M_2021"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        base_url: str = "https://services.sentinel-hub.com",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def _get_token(self) -> str:
        """Fetch an OAuth2 token from Sentinel Hub (cached until near expiry)."""
        now = asyncio.get_event_loop().time()
        if self._token and now < self._token_expiry - 60:
            return self._token

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base_url}/auth/realms/main/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body["access_token"]
            self._token_expiry = now + body.get("expires_in", 3600)
            return self._token  # type: ignore[return-value]

    async def classify(self, geojson_polygon: dict) -> LandCoverResult:
        if not self._client_id or not self._client_secret:
            # No credentials — return "unavailable" so the pipeline refuses to attest
            return LandCoverResult(
                dominant_class=0,
                dominant_label="Unknown",
                class_fractions={},
                is_water=False,
                available=False,
                evidence={"error": "Sentinel Hub credentials not configured"},
            )

        try:
            token = await self._get_token()
        except Exception as exc:
            return LandCoverResult(
                dominant_class=0,
                dominant_label="Unknown",
                class_fractions={},
                is_water=False,
                available=False,
                evidence={"error": f"Sentinel Hub auth failed: {exc}"},
            )

        # Evalscript: return the WorldCover class value as a single band.
        evalscript = """
//VERSION=3
function setup() {
  return {
    input: [{ datasource: "worldcover", bands: ["Map"] }],
    output: [{ id: "default", bands: 1 }]
  };
}
function evaluatePixel(samples) {
  return [samples.worldcover.Map];
}
"""

        payload = {
            "input": {
                "bounds": {
                    "geometry": geojson_polygon,
                    "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
                },
                "data": [
                    {
                        "dataFilter": {"timeRange": {"from": "2021-01-01T00:00:00Z", "to": "2021-12-31T23:59:59Z"}},
                        "type": self.WORLDCOVER_COLLECTION,
                        "id": "worldcover",
                    }
                ],
            },
            "aggregation": {
                "timeRange": {"from": "2021-01-01T00:00:00Z", "to": "2021-12-31T23:59:59Z"},
                "aggregationInterval": {"of": "P1D"},
                "evalscript": evalscript,
                "resx": 10,
                "resy": 10,
            },
            "calculations": {
                "default": {
                    "histograms": {
                        "default": {"lowEdge": 0, "highEdge": 110, "numberOfBins": 111}
                    }
                }
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._base_url}/api/v1/statistics",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return LandCoverResult(
                dominant_class=0,
                dominant_label="Unknown",
                class_fractions={},
                is_water=False,
                available=False,
                evidence={"error": f"Sentinel Hub statistics call failed: {exc}"},
            )

        # Parse histogram — bins map to WorldCover class codes (bin index = class value)
        try:
            intervals = data["data"][0]["outputs"]["default"]["bands"]["B0"]["histogram"]["bins"]
            counts: dict[int, int] = {}
            for i, entry in enumerate(intervals):
                count = entry.get("count", 0)
                if count > 0:
                    counts[i] = count

            total = sum(counts.values()) or 1
            fractions = {cls: cnt / total for cls, cnt in counts.items()}
            dominant = max(fractions, key=lambda c: fractions[c]) if fractions else 0
        except (KeyError, IndexError):
            return LandCoverResult(
                dominant_class=0,
                dominant_label="Unknown",
                class_fractions={},
                is_water=False,
                available=False,
                evidence={"error": "Could not parse WorldCover histogram", "raw": data},
            )

        return LandCoverResult(
            dominant_class=dominant,
            dominant_label=WORLDCOVER_LABELS.get(dominant, "Unknown"),
            class_fractions=fractions,
            is_water=(dominant == 80),
            available=True,
            evidence={"histogram": fractions, "total_pixels": total},
        )
