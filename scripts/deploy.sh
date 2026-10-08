#!/usr/bin/env bash
# deploy.sh — Build and deploy all three Cadaster contracts to Stellar testnet
#
# Prerequisites
# ─────────────
#   stellar CLI  https://developers.stellar.org/docs/tools/stellar-cli
#   Rust + cargo, target wasm32-unknown-unknown
#   A funded testnet account (script will fund via Friendbot if needed)
#
# Usage
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh [--account <KEYPAIR_NAME>]
#
# The script prints all three contract IDs at the end and writes them to
# .env.contracts so the agent and frontend can read them.
set -euo pipefail

NETWORK="testnet"
ACCOUNT="${ACCOUNT:-cadaster-deployer}"
CONTRACTS_DIR="$(cd "$(dirname "$0")/../contracts" && pwd)"
OUT_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env.contracts"

log()  { echo "▶ $*"; }
die()  { echo "✗ $*" >&2; exit 1; }

# ─── 0. Sanity checks ─────────────────────────────────────────────────────────

command -v stellar >/dev/null 2>&1 || die "stellar CLI not found. Install from https://github.com/stellar/stellar-cli"
command -v cargo   >/dev/null 2>&1 || die "cargo not found"

# ─── 1. Generate / fund deployer account ────────────────────────────────────

if ! stellar keys show "$ACCOUNT" >/dev/null 2>&1; then
    log "Generating keypair '$ACCOUNT'..."
    stellar keys generate "$ACCOUNT" --network "$NETWORK"
fi

ADDR=$(stellar keys address "$ACCOUNT")
log "Deployer address: $ADDR"

log "Funding via Friendbot..."
stellar keys fund "$ACCOUNT" --network "$NETWORK" || log "(already funded or Friendbot unavailable — continuing)"

# ─── 2. Build all contracts ────────────────────────────────────────────────

log "Building contracts (release, wasm32)..."
(
    cd "$CONTRACTS_DIR"
    cargo build --release --target wasm32-unknown-unknown 2>&1
)

WASM_DIR="$CONTRACTS_DIR/target/wasm32-unknown-unknown/release"

REGISTRY_WASM="$WASM_DIR/cadaster_attester_registry.wasm"
VERIFIER_WASM="$WASM_DIR/cadaster_verifier.wasm"
TOKEN_WASM="$WASM_DIR/cadaster_token.wasm"

[[ -f "$REGISTRY_WASM" ]] || die "Registry WASM not found: $REGISTRY_WASM"
[[ -f "$VERIFIER_WASM" ]] || die "Verifier WASM not found: $VERIFIER_WASM"
[[ -f "$TOKEN_WASM"    ]] || die "Token WASM not found: $TOKEN_WASM"

# ─── 3. Optimize with wasm-opt (optional, skip if not installed) ─────────────

if command -v wasm-opt >/dev/null 2>&1; then
    log "Optimizing WASM with wasm-opt..."
    wasm-opt -Oz -o "$REGISTRY_WASM" "$REGISTRY_WASM"
    wasm-opt -Oz -o "$VERIFIER_WASM" "$VERIFIER_WASM"
    wasm-opt -Oz -o "$TOKEN_WASM"    "$TOKEN_WASM"
else
    log "wasm-opt not found — skipping optimisation (install binaryen for smaller contracts)"
fi

# ─── 4. Deploy cadaster-attester-registry ────────────────────────────────────

log "Deploying cadaster-attester-registry..."
REGISTRY_ID=$(stellar contract deploy \
    --wasm "$REGISTRY_WASM" \
    --source "$ACCOUNT" \
    --network "$NETWORK")
log "  Registry ID: $REGISTRY_ID"

# Initialise: set deployer as admin
log "Initialising registry (admin = $ADDR)..."
stellar contract invoke \
    --id "$REGISTRY_ID" \
    --source "$ACCOUNT" \
    --network "$NETWORK" \
    -- init \
    --admin "$ADDR"

# ─── 5. Deploy cadaster-verifier ─────────────────────────────────────────────

log "Deploying cadaster-verifier..."
VERIFIER_ID=$(stellar contract deploy \
    --wasm "$VERIFIER_WASM" \
    --source "$ACCOUNT" \
    --network "$NETWORK")
log "  Verifier ID: $VERIFIER_ID"

log "Initialising verifier (registry = $REGISTRY_ID)..."
stellar contract invoke \
    --id "$VERIFIER_ID" \
    --source "$ACCOUNT" \
    --network "$NETWORK" \
    -- init \
    --registry "$REGISTRY_ID"

# ─── 6. Deploy cadaster-token ─────────────────────────────────────────────────

log "Deploying cadaster-token..."
TOKEN_ID=$(stellar contract deploy \
    --wasm "$TOKEN_WASM" \
    --source "$ACCOUNT" \
    --network "$NETWORK")
log "  Token ID: $TOKEN_ID"

log "Initialising token (admin = $ADDR, verifier = $VERIFIER_ID)..."
stellar contract invoke \
    --id "$TOKEN_ID" \
    --source "$ACCOUNT" \
    --network "$NETWORK" \
    -- init \
    --admin "$ADDR" \
    --verifier "$VERIFIER_ID"

# ─── 7. Register the attester key ────────────────────────────────────────────
#
# The ATTESTER_PUBKEY must be the Ed25519 public key (hex, 32 bytes) that the
# Python agent uses for signing.  Set ATTESTER_PUBKEY in environment before
# running this script, or add it manually afterwards with:
#
#   stellar contract invoke --id $REGISTRY_ID --source cadaster-deployer \
#       --network testnet -- add_attester --pubkey <HEX_PUBKEY>

if [[ -n "${ATTESTER_PUBKEY:-}" ]]; then
    log "Registering attester key: $ATTESTER_PUBKEY"
    stellar contract invoke \
        --id "$REGISTRY_ID" \
        --source "$ACCOUNT" \
        --network "$NETWORK" \
        -- add_attester \
        --pubkey "$ATTESTER_PUBKEY"
else
    log "ATTESTER_PUBKEY not set — skip registering attester key."
    log "  Run: stellar contract invoke --id $REGISTRY_ID --source $ACCOUNT \\"
    log "       --network testnet -- add_attester --pubkey <32_BYTE_HEX>"
fi

# ─── 8. Write contract IDs to .env.contracts ─────────────────────────────────

cat > "$OUT_FILE" <<EOF
# Auto-generated by scripts/deploy.sh — $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Commit or save these; they are needed by the agent and frontend.

NEXT_PUBLIC_REGISTRY_CONTRACT_ID=$REGISTRY_ID
NEXT_PUBLIC_VERIFIER_CONTRACT_ID=$VERIFIER_ID
NEXT_PUBLIC_TOKEN_CONTRACT_ID=$TOKEN_ID
STELLAR_NETWORK=testnet
EOF

log ""
log "════════════════════════════════════════════════════════"
log "  Deployment complete!"
log ""
log "  Registry  : $REGISTRY_ID"
log "  Verifier  : $VERIFIER_ID"
log "  Token     : $TOKEN_ID"
log ""
log "  Written to: $OUT_FILE"
log "════════════════════════════════════════════════════════"
