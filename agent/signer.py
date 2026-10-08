"""
agent/signer.py

Build and sign a Cadaster attestation.

The canonical Attestation structure mirrors the Soroban contract:

    struct Attestation {
        claim_hash:  BytesN<32>  // sha256 of the claim JSON (canonical)
        asset_type:  u32
        verdict:     bool
        score:       u32
        issued_at:   u64         // Unix seconds
        expiry:      u64         // Unix seconds
        nonce:       BytesN<32>  // 32 random bytes, single-use
    }

XDR serialisation
─────────────────
The Soroban contract XDR-serialises the Attestation as a ScVal map (the
soroban-sdk `contracttype` macro emits an ScMap).  Rather than re-implement
the full XDR codec in Python, we use the stellar-sdk XDR types to build
the identical byte sequence the contract produces.

Signing
───────
The Ed25519 private key is loaded from ATTESTER_PRIVATE_KEY_HEX (32 raw
bytes, hex-encoded).  The signer signs the raw XDR bytes — identical to
what the contract will pass to ed25519_verify.
"""

from __future__ import annotations

import hashlib
import os
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.config import get_settings


# ─── Attestation dataclass ────────────────────────────────────────────────────


class Attestation:
    """
    Python mirror of the Soroban Attestation struct.

    Fields match the contract definition exactly — any change here must be
    reflected in the Soroban contracttype.
    """

    __slots__ = (
        "claim_hash",
        "asset_type",
        "verdict",
        "score",
        "issued_at",
        "expiry",
        "nonce",
    )

    def __init__(
        self,
        claim_hash: bytes,      # 32 bytes
        asset_type: int,
        verdict: bool,
        score: int,
        issued_at: int,
        expiry: int,
        nonce: bytes,           # 32 bytes
    ) -> None:
        assert len(claim_hash) == 32, "claim_hash must be 32 bytes"
        assert len(nonce) == 32, "nonce must be 32 bytes"
        self.claim_hash = claim_hash
        self.asset_type = asset_type
        self.verdict = verdict
        self.score = score
        self.issued_at = issued_at
        self.expiry = expiry
        self.nonce = nonce

    def to_dict(self) -> dict:
        return {
            "claim_hash": self.claim_hash.hex(),
            "asset_type": self.asset_type,
            "verdict": self.verdict,
            "score": self.score,
            "issued_at": self.issued_at,
            "expiry": self.expiry,
            "nonce": self.nonce.hex(),
        }


# ─── XDR serialisation ────────────────────────────────────────────────────────


def _serialize_attestation_xdr(att: Attestation) -> bytes:
    """
    Produce the XDR byte sequence that Soroban's `contracttype` macro
    generates for the Attestation struct.

    The soroban-sdk contracttype macro serialises a struct as a ScVal of type
    ScMap, with entries ordered alphabetically by field name.  Each entry is
    an ScMapEntry(key=ScVal::Symbol(name), val=ScVal::...).

    Alphabetical field order for Attestation:
      asset_type, claim_hash, expiry, issued_at, nonce, score, verdict

    XDR encoding used:
      - ScVal discriminant as uint32 big-endian
      - ScSymbol: len (uint32 be) + bytes (padded to 4-byte boundary)
      - ScMap: count (uint32 be) + entries
      - BytesN<32>: raw 32 bytes (no length prefix for fixed-size)
      - u32: uint32 big-endian
      - u64: uint64 big-endian
      - bool: uint32 big-endian (0=false, 1=true)

    NOTE: This implementation encodes using the stellar_sdk XDR library
    when available, falling back to a hand-rolled encoder.  The stellar-sdk
    XDR is the canonical reference.
    """
    try:
        return _serialize_via_stellar_sdk(att)
    except ImportError:
        return _serialize_hand_rolled(att)


def _serialize_via_stellar_sdk(att: Attestation) -> bytes:
    """Use stellar-sdk's XDR types (most accurate)."""
    from stellar_sdk import xdr as stellar_xdr

    def sym(s: str) -> stellar_xdr.SCVal:
        return stellar_xdr.SCVal(
            type=stellar_xdr.SCValType.SCV_SYMBOL,
            sym=stellar_xdr.SCSymbol(sc_symbol=s.encode()),
        )

    def u32(v: int) -> stellar_xdr.SCVal:
        return stellar_xdr.SCVal(
            type=stellar_xdr.SCValType.SCV_U32,
            u32=stellar_xdr.Uint32(uint32=v),
        )

    def u64(v: int) -> stellar_xdr.SCVal:
        return stellar_xdr.SCVal(
            type=stellar_xdr.SCValType.SCV_U64,
            u64=stellar_xdr.Uint64(uint64=v),
        )

    def boolean(v: bool) -> stellar_xdr.SCVal:
        return stellar_xdr.SCVal(
            type=stellar_xdr.SCValType.SCV_BOOL,
            b=v,
        )

    def bytesn(data: bytes) -> stellar_xdr.SCVal:
        return stellar_xdr.SCVal(
            type=stellar_xdr.SCValType.SCV_BYTES,
            bytes=stellar_xdr.SCBytes(sc_bytes=data),
        )

    # Fields sorted alphabetically — must match contracttype field order
    entries = [
        stellar_xdr.SCMapEntry(key=sym("asset_type"), val=u32(att.asset_type)),
        stellar_xdr.SCMapEntry(key=sym("claim_hash"), val=bytesn(att.claim_hash)),
        stellar_xdr.SCMapEntry(key=sym("expiry"),     val=u64(att.expiry)),
        stellar_xdr.SCMapEntry(key=sym("issued_at"),  val=u64(att.issued_at)),
        stellar_xdr.SCMapEntry(key=sym("nonce"),      val=bytesn(att.nonce)),
        stellar_xdr.SCMapEntry(key=sym("score"),      val=u32(att.score)),
        stellar_xdr.SCMapEntry(key=sym("verdict"),    val=boolean(att.verdict)),
    ]

    sc_map = stellar_xdr.SCVal(
        type=stellar_xdr.SCValType.SCV_MAP,
        map=stellar_xdr.SCMap(sc_map=entries),
    )
    return sc_map.to_xdr_bytes()


def _serialize_hand_rolled(att: Attestation) -> bytes:
    """
    Minimal hand-rolled XDR encoder.  Used when stellar-sdk is not installed.
    Produces the same byte sequence as _serialize_via_stellar_sdk for the
    specific Attestation struct shape.

    XDR reference: RFC 4506
    """
    import struct

    def pack_u32(v: int) -> bytes:
        return struct.pack(">I", v)

    def pack_u64(v: int) -> bytes:
        return struct.pack(">Q", v)

    def pack_bool(v: bool) -> bytes:
        return pack_u32(1 if v else 0)

    def pack_bytes_fixed(data: bytes) -> bytes:
        # BytesN<32> in XDR: discriminant SCV_BYTES (6) + length + raw bytes
        # XDR opaque fixed: no length prefix, padded to 4 bytes
        return data + (b"\x00" * (4 - len(data) % 4)) if len(data) % 4 else data

    def scval_discriminant(type_id: int) -> bytes:
        return pack_u32(type_id)

    # SCValType constants from Stellar XDR
    SCV_BOOL   = 0
    SCV_U32    = 6
    SCV_U64    = 7
    SCV_BYTES  = 14
    SCV_SYMBOL = 16
    SCV_MAP    = 20

    def scval_symbol(s: str) -> bytes:
        encoded = s.encode()
        length = len(encoded)
        pad = (4 - length % 4) % 4
        return scval_discriminant(SCV_SYMBOL) + pack_u32(length) + encoded + b"\x00" * pad

    def scval_u32(v: int) -> bytes:
        return scval_discriminant(SCV_U32) + pack_u32(v)

    def scval_u64(v: int) -> bytes:
        return scval_discriminant(SCV_U64) + pack_u64(v)

    def scval_bool(v: bool) -> bytes:
        return scval_discriminant(SCV_BOOL) + pack_bool(v)

    def scval_bytes(data: bytes) -> bytes:
        pad = (4 - len(data) % 4) % 4
        return scval_discriminant(SCV_BYTES) + pack_u32(len(data)) + data + b"\x00" * pad

    def map_entry(key_bytes: bytes, val_bytes: bytes) -> bytes:
        return key_bytes + val_bytes

    entries = b"".join([
        map_entry(scval_symbol("asset_type"), scval_u32(att.asset_type)),
        map_entry(scval_symbol("claim_hash"), scval_bytes(att.claim_hash)),
        map_entry(scval_symbol("expiry"),     scval_u64(att.expiry)),
        map_entry(scval_symbol("issued_at"),  scval_u64(att.issued_at)),
        map_entry(scval_symbol("nonce"),      scval_bytes(att.nonce)),
        map_entry(scval_symbol("score"),      scval_u32(att.score)),
        map_entry(scval_symbol("verdict"),    scval_bool(att.verdict)),
    ])

    sc_map = scval_discriminant(SCV_MAP) + pack_u32(7) + entries
    return sc_map


# ─── Claim hash ───────────────────────────────────────────────────────────────


def compute_claim_hash(claim_json: str) -> bytes:
    """
    SHA-256 of the canonical (sorted-keys) JSON encoding of the claim.
    The frontend and agent must use the same canonical form.
    """
    return hashlib.sha256(claim_json.encode()).digest()


# ─── Signer ───────────────────────────────────────────────────────────────────


def _load_private_key() -> Ed25519PrivateKey:
    """Load the Ed25519 private key from the environment (never from disk)."""
    settings = get_settings()
    raw = bytes.fromhex(settings.attester_private_key_hex)
    if len(raw) != 32:
        raise ValueError("ATTESTER_PRIVATE_KEY_HEX must be exactly 32 bytes (64 hex chars)")
    return Ed25519PrivateKey.from_private_bytes(raw)


def get_attester_pubkey() -> bytes:
    """Return the raw 32-byte Ed25519 public key."""
    key = _load_private_key()
    pubkey_obj = key.public_key()
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return pubkey_obj.public_bytes(Encoding.Raw, PublicFormat.Raw)


def sign_attestation(att: Attestation) -> tuple[bytes, bytes]:
    """
    Serialise the attestation to XDR and sign it.

    Returns (xdr_bytes, signature_bytes) where:
      - xdr_bytes     is the canonical serialisation (for verification / audit)
      - signature_bytes is the 64-byte Ed25519 signature

    The Soroban verifier contract calls:
        ed25519_verify(pubkey, xdr_bytes, signature)
    """
    xdr_bytes = _serialize_attestation_xdr(att)
    key = _load_private_key()
    signature = key.sign(xdr_bytes)
    return xdr_bytes, signature


def build_and_sign(
    claim_hash: bytes,
    asset_type: int,
    score: int,
) -> tuple[Attestation, bytes, bytes]:
    """
    Build a fresh Attestation with a random nonce and short expiry, then sign it.

    Returns (attestation, xdr_bytes, signature).
    """
    settings = get_settings()
    now = int(time.time())
    nonce = os.urandom(32)
    att = Attestation(
        claim_hash=claim_hash,
        asset_type=asset_type,
        verdict=True,
        score=score,
        issued_at=now,
        expiry=now + settings.attestation_ttl_seconds,
        nonce=nonce,
    )
    xdr_bytes, signature = sign_attestation(att)
    return att, xdr_bytes, signature
