<p align="center">
  <img src="assets/logo.svg" alt="Cadaster" width="320" />
</p>

<p align="center">
  <strong>Geo-verification oracle for RWA tokenization on Stellar.</strong><br>
  An agent checks claimed coordinates against satellite data and signs an attestation before minting.
</p>

<p align="center">
  <a href="https://github.com/Cadaster-ii/Cadaster/actions/workflows/ci.yml">
    <img src="https://github.com/Cadaster-ii/Cadaster/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT">
  </a>
</p>

---

## The problem

Real-world assets (RWA) tokenized on-chain are only as trustworthy as the off-chain data attached to them. For land parcels the gap is especially wide: anyone can submit coordinates and mint a "land token" with no check that the claimed location is actually land, in the claimed country, or not already tokenized by someone else. Without a verifiable link to ground truth, RWA tokens are just IOUs dressed as deeds.

## How it works

```
Asset owner                 Cadaster Agent                  Stellar / Soroban
──────────                  ──────────────                  ─────────────────
Submit GeoJSON polygon  →   Run geo-checks:                 cadaster-attester-registry
+ country code              • polygon sanity (Shapely)        stores authorised keys
                            • land vs water (WorldCover)
                            • country match (Nominatim)    cadaster-verifier
                            • land-use classification        verifies Ed25519 sig
                            • duplicate/overlap (PostGIS)    checks expiry & nonce
                                    │                        rejects replays
                              all pass? ↓ yes
                            Build Attestation struct
                            Sign sha(xdr(attestation))     cadaster-token (SEP-41)
                                    │                        calls verifier.verify()
                            Return attestation + sig   →    mints 1 CDSTR token
                                                            records claim_hash
```

**The agent signs, the contract verifies.** The private key never touches the chain. The contract is the single point of authority — it recomputes the canonical message and verifies the signature itself. Replacing or upgrading the agent does not compromise already-minted tokens.

## Architecture

```
/contracts
  cadaster-attester-registry   Stores authorised Ed25519 public keys (admin-controlled)
  cadaster-verifier            Verifies attestations; burns nonces; independent of the token
  cadaster-token               SEP-41 token; mint() gates on verifier.verify()

/agent                         Python FastAPI service
  providers/                   Swappable data-source interfaces
    geocoder.py                OSM Nominatim (reverse geocoding)
    land_cover.py              ESA WorldCover via Sentinel Hub
  checks/                      Deterministic check functions
    polygon_sanity.py          Coordinate range, closure, self-intersection, area
    land_checks.py             Land/water, country match, land-use type
    duplicate_check.py         Overlap with previously attested polygons
  signer.py                    Builds canonical XDR; signs with Ed25519 private key
  main.py                      FastAPI app — POST /verify, POST /attest

/web                           Next.js 15 demo frontend
  MapDrawer.tsx                Leaflet polygon drawing (SSR-disabled)
  ChecksPanel.tsx              Verification check results
  WalletButton.tsx             Freighter wallet via stellar-wallets-kit
  stellar.ts                   Builds and submits mint() via @stellar/stellar-sdk
```

## Quickstart (free data tiers)

### Prerequisites

- Rust 1.81+ with `wasm32-unknown-unknown` target
- `stellar` CLI — [install guide](https://developers.stellar.org/docs/tools/stellar-cli)
- Python 3.11+
- Node.js 20+
- PostgreSQL with PostGIS (for overlap checks; optional for basic verify)

### 1. Smart contracts

```bash
cd contracts
cargo test --features testutils          # 17 tests across 3 crates

# Deploy to testnet (requires funded testnet account)
cd ..
./scripts/deploy.sh
# Prints contract IDs and writes .env.contracts
```

### 2. Agent

```bash
cd agent
cp ../.env.example .env
# Fill in ATTESTER_PRIVATE_KEY_HEX (generate with: openssl rand -hex 32)
# Optionally add Sentinel Hub credentials for land-cover checks

pip install -r requirements.txt
uvicorn agent.main:app --reload

# Run tests
python -m pytest
```

### 3. Frontend

```bash
cd web
cp .env.local.example .env.local
# Paste contract IDs from .env.contracts into NEXT_PUBLIC_TOKEN_CONTRACT_ID etc.

npm install
npm run dev
# Open http://localhost:3000
```

### Register the attester key

After deploying, register the agent's public key in the registry:

```bash
# Get the pubkey from the running agent
curl http://localhost:8000/pubkey

# Register it on-chain
stellar contract invoke \
  --id $REGISTRY_CONTRACT_ID \
  --source cadaster-deployer \
  --network testnet \
  -- add_attester --pubkey <HEX_PUBKEY>
```

## Testnet contract IDs

> Deploy and paste your own IDs here after running `./scripts/deploy.sh`.

| Contract | Testnet ID |
|---|---|
| cadaster-attester-registry | _pending deploy_ |
| cadaster-verifier | _pending deploy_ |
| cadaster-token (CDSTR) | _pending deploy_ |

## Demo

![Demo GIF placeholder — record and replace with your own](assets/demo.gif)

## Project structure

```
Cadaster/
├── assets/
│   └── logo.svg
├── contracts/
│   ├── Cargo.toml                      workspace
│   ├── cadaster-attester-registry/
│   ├── cadaster-verifier/
│   └── cadaster-token/
├── agent/
│   ├── requirements.txt
│   ├── config.py
│   ├── main.py
│   ├── signer.py
│   ├── db.py
│   ├── providers/
│   └── checks/
├── web/
│   ├── package.json
│   └── src/
├── scripts/
│   └── deploy.sh
├── .env.example
├── .github/workflows/ci.yml
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
└── LICENSE
```

## Design principles

1. **Deterministic checks decide the verdict.** If an LLM is ever added, it may only summarise evidence or flag ambiguous cases for human review — it must never hold signing authority or influence pass/fail.
2. **No attestation is the safe default.** On any doubt — unavailable data source, low confidence, check failure — the agent refuses to sign.
3. **The verifier is independent.** Other projects can reuse `cadaster-verifier` without the token. It verifies any Ed25519 attestation against a registry.
4. **The agent signs, the contract verifies.** The agent's role is advisory and replaceable. All on-chain authority lives in the contract.

## Roadmap

| Phase | Scope |
|---|---|
| v0.1 MVP | Land parcel verification (this release) |
| v0.2 | Commodity & agricultural land sub-types |
| v0.3 | Carbon credit / forest cover verification |
| v1.0 | M-of-N attester multi-sig; attester reputation scoring |
| v1.x | ZK-proof of geo-check for privacy-preserving land claims |

## License

MIT — see [LICENSE](LICENSE).
