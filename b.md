# Wave Program — Issue Types for Cadaster

## Bug fixes (`complexity: trivial` → `medium`)

- **XDR field ordering regression** — if anyone adds a field to `Attestation`, the alphabetical sort in `signer.py`'s hand-rolled encoder must stay in sync with the Soroban contracttype. A mismatch silently breaks all signatures. Add a cross-language test that catches drift.
- **Leaflet icon 404 in production** — the MapDrawer currently hotlinks Leaflet marker icons from unpkg. Replace with bundled assets so it works offline/air-gapped.
- **Nominatim rate-limit race** — the 1 req/s guard in `NominatimGeocoder` uses `get_event_loop().time()` which breaks under some async runners. Switch to `asyncio.monotonic` / a proper token-bucket.
- **`parcel_already_minted` check gap** — the token contract guards against re-minting the same `claim_hash`, but the agent doesn't pre-check this before calling the chain, so the user gets an opaque trap instead of a clear error. Agent should query the contract first.

---

## New features (`complexity: medium` → `high`)

- **Alembic migration** — `db.py` defines the `AttestedPolygon` ORM model but there are no migration files. Write the initial Alembic migration including a PostGIS `Geometry(Polygon, 4326)` column and GiST spatial index (replaces the current WKT fallback).
- **`POST /attest` idempotency** — if the same claim hash is submitted twice (e.g. a retry after a network drop), the agent currently issues a second attestation with a new nonce. Add a cache layer that returns the original attestation within its TTL.
- **Sentinel Hub fallback to GEE** — implement a second `LandCoverProvider` backed by the Google Earth Engine public datasets API, so land-cover checks degrade gracefully when Sentinel Hub quota is exhausted.
- **`GET /attestation/{claim_hash}`** — retrieve stored attestation evidence by claim hash. Useful for auditors and the frontend's "view parcel history" flow.
- **`transfer` updates parcel owner** — the token contract's `transfer()` moves the balance but doesn't update `ParcelOwner`. Either prohibit transfers (making tokens non-transferable deeds) or keep the registry in sync. Design decision needed.
- **M-of-N attester multi-sig** (v1.0 roadmap) — replace the single-key registry with a threshold signature scheme in the verifier contract.

---

## Testing (`complexity: trivial` → `medium`)

- **Integration test: full `/attest` flow with mocked providers** — the current Python tests cover checks in isolation but nothing exercises `main.py` end-to-end. Write a `TestClient` test that mocks both providers and a fake DB session.
- **Rust property-based tests** — use `proptest` to fuzz `Attestation` field boundaries (score > 100, nonce all-zeros, expiry in the past by 1 second) and confirm the verifier traps correctly.
- **Duplicate-check test with real PostGIS** — the current overlap tests use Shapely only. Add a pytest fixture that spins up PostGIS via `pytest-docker` and exercises the DB path.
- **Frontend smoke test** — add a Playwright test that loads the page, confirms the map renders, and checks the Verify button is disabled when no polygon is drawn.

---

## Documentation (`complexity: trivial`)

- **Fill in testnet contract IDs** — the README table has `_pending deploy_` placeholders. After a real testnet deploy, update these and document the deploy date/network.
- **`signer.py` XDR spec doc** — the canonical serialisation format is security-critical but only explained in inline comments. Write a standalone `docs/attestation-xdr.md` with the exact byte layout, field order rationale, and a worked example.
- **Provider swap guide** — document how to plug in an alternative geocoder (e.g. Pelias) or land-cover source (e.g. Google Earth Engine) by implementing the abstract interface.
- **Demo GIF** — record the full flow (draw → verify → attest → mint on testnet) and replace the placeholder in the README.

---

## Chores / DevEx (`complexity: trivial`)

- **`ruff` config** — add `pyproject.toml` with `[tool.ruff]` so `ruff format` and `ruff check` are enforced consistently in CI.
- **`cargo clippy` in CI** — the contracts job currently only runs tests and builds. Add `cargo clippy -- -D warnings` to catch lint issues early.
- **Pin `npm` deps with lockfile** — `web/package-lock.json` isn't committed, so `npm ci` in CI will fail. Either commit the lockfile or switch the CI step to `npm install`.
- **`wasm-opt` in CI** — the deploy script calls `wasm-opt` if present but CI skips it. Add `binaryen` to the contracts job so contract sizes are verified on every build.
