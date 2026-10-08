//! cadaster-verifier  (soroban-sdk 29)
//!
//! Verifies an off-chain Ed25519 attestation before allowing any downstream
//! contract (e.g. cadaster-token) to act on it.
//!
//! Security model
//! ──────────────
//!  1. The canonical message is `xdr_serialize(Attestation)`.
//!     The contract always recomputes this — it never trusts a caller-supplied hash.
//!  2. The signer's public key must be registered in cadaster-attester-registry.
//!  3. `expiry` must be > current ledger timestamp.
//!  4. Each `nonce` can only be consumed once (stored in Persistent storage).
//!     Replaying a nonce causes a panic.
//!
//! The contract exposes `verify` which returns the claim hash on success and
//! panics (traps) on any security violation so callers receive a clean error.

#![no_std]

use soroban_sdk::{
    contract, contractimpl, contracttype, symbol_short, xdr::ToXdr, Address, Bytes, BytesN, Env,
};

// ─── Re-export so cadaster-token can import Attestation from one place ────────

pub use attestation::Attestation;

// ─── Attestation type ─────────────────────────────────────────────────────────

pub mod attestation {
    use soroban_sdk::{contracttype, BytesN};

    /// The canonical record that the off-chain agent builds and signs.
    ///
    /// `asset_type`: 1 = land parcel (only type in MVP).
    /// `score`: 0–100 confidence score produced by the geo-checks.
    /// `verdict`: true = all checks passed.
    /// `issued_at` / `expiry`: Unix seconds (ledger timestamp units).
    /// `nonce`: 32 random bytes, single-use.
    #[contracttype]
    #[derive(Clone, Debug, PartialEq, Eq)]
    pub struct Attestation {
        pub claim_hash: BytesN<32>,
        pub asset_type: u32,
        pub verdict: bool,
        pub score: u32,
        pub issued_at: u64,
        pub expiry: u64,
        pub nonce: BytesN<32>,
    }
}

// ─── Storage keys ─────────────────────────────────────────────────────────────

#[contracttype]
pub enum DataKey {
    /// Address of the deployed cadaster-attester-registry contract.
    Registry,
    /// Marks a nonce as consumed.  Value type is irrelevant; presence = used.
    Nonce(BytesN<32>),
}

// ─── Contract ─────────────────────────────────────────────────────────────────

#[contract]
pub struct Verifier;

#[contractimpl]
impl Verifier {
    // ── Initialisation ────────────────────────────────────────────────────────

    /// One-time setup: record the registry contract address.
    pub fn init(env: Env, registry: Address) {
        if env.storage().instance().has(&DataKey::Registry) {
            panic!("already initialised");
        }
        env.storage().instance().set(&DataKey::Registry, &registry);
    }

    // ── Core verification ─────────────────────────────────────────────────────

    /// Verify an attestation and consume its nonce.
    ///
    /// Returns the `claim_hash` on success.
    /// Panics (traps) on any security violation so callers receive a clean error.
    pub fn verify(
        env: Env,
        attestation: Attestation,
        pubkey: BytesN<32>,
        signature: BytesN<64>,
    ) -> BytesN<32> {
        // 1. Require the key to be registered ─────────────────────────────────
        let registry: Address = env
            .storage()
            .instance()
            .get(&DataKey::Registry)
            .expect("verifier not initialised");

        let reg_client =
            cadaster_attester_registry::AttesterRegistryClient::new(&env, &registry);

        if !reg_client.is_attester(&pubkey) {
            panic!("unregistered attester key");
        }

        // 2. Check attestation is not expired ─────────────────────────────────
        let now = env.ledger().timestamp();
        if attestation.expiry <= now {
            panic!("attestation expired");
        }

        // 3. Check verdict ─────────────────────────────────────────────────────
        if !attestation.verdict {
            panic!("attestation verdict is false");
        }

        // 4. Check nonce not yet consumed ─────────────────────────────────────
        let nonce_key = DataKey::Nonce(attestation.nonce.clone());
        if env.storage().persistent().has(&nonce_key) {
            panic!("nonce already used (replay attack)");
        }

        // 5. Reconstruct canonical message and verify signature ───────────────
        //    message = xdr_serialize(attestation)
        //    ed25519_verify uses RFC 8032 signing (no pre-hashing by caller)
        let serialized: Bytes = attestation.clone().to_xdr(&env);

        // Soroban host function: panics if signature is invalid
        env.crypto()
            .ed25519_verify(&pubkey, &serialized, &signature);

        // 6. Burn the nonce ────────────────────────────────────────────────────
        env.storage().persistent().set(&nonce_key, &true);

        // Emit an event so indexers can track verifications
        env.events().publish(
            (symbol_short!("verified"), pubkey),
            attestation.claim_hash.clone(),
        );

        attestation.claim_hash
    }

    /// Read the registry address (useful for cross-contract calls).
    pub fn registry(env: Env) -> Address {
        env.storage()
            .instance()
            .get(&DataKey::Registry)
            .expect("not initialised")
    }
}

// ─── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    extern crate std;

    use super::attestation::Attestation;
    use super::*;
    use cadaster_attester_registry::{AttesterRegistry, AttesterRegistryClient};
    use soroban_sdk::{
        testutils::{Address as _, Ledger},
        xdr::ToXdr,
        BytesN, Env,
    };

    // ── ed25519 test key pair (deterministic, for tests only) ─────────────────
    // RFC 8032 test vector #1 private key seed — DO NOT USE IN PRODUCTION.
    const TEST_PRIVKEY_SEED: [u8; 32] = [
        0x9d, 0x61, 0xb1, 0x9d, 0xef, 0xfd, 0x5a, 0x60,
        0xba, 0x84, 0x4a, 0xf4, 0x92, 0xec, 0x2c, 0x44,
        0xd7, 0x36, 0xf5, 0xb0, 0x25, 0x75, 0x49, 0x27,
        0x37, 0x80, 0xb4, 0x00, 0x9a, 0x9d, 0xf9, 0xb4,
    ];

    fn signing_key() -> ed25519_dalek::SigningKey {
        ed25519_dalek::SigningKey::from_bytes(&TEST_PRIVKEY_SEED)
    }

    fn pubkey_bytes(env: &Env) -> BytesN<32> {
        let vk = signing_key().verifying_key();
        BytesN::from_array(env, vk.as_bytes())
    }

    /// Sign the canonical XDR serialisation of an attestation.
    fn sign_attestation(env: &Env, attestation: &Attestation) -> BytesN<64> {
        use ed25519_dalek::Signer;
        let serialized = attestation.clone().to_xdr(env);
        // Collect Bytes into a Vec<u8> — only valid in test (std) context
        let mut buf = std::vec![0u8; serialized.len() as usize];
        serialized.copy_into_slice(&mut buf);
        let sig = signing_key().sign(&buf);
        BytesN::from_array(env, &sig.to_bytes())
    }

    fn make_attestation(env: &Env, nonce_byte: u8) -> Attestation {
        Attestation {
            claim_hash: BytesN::from_array(env, &[0xab; 32]),
            asset_type: 1,
            verdict: true,
            score: 90,
            issued_at: 1_000,
            expiry: 2_000,
            nonce: BytesN::from_array(env, &[nonce_byte; 32]),
        }
    }

    fn setup() -> (Env, VerifierClient<'static>, BytesN<32>) {
        let env = Env::default();
        env.mock_all_auths();

        // Set ledger timestamp so attestations are not yet expired
        env.ledger().with_mut(|l| l.timestamp = 1_500);

        // Deploy registry
        let reg_id = env.register(AttesterRegistry, ());
        let reg_client = AttesterRegistryClient::new(&env, &reg_id);
        let admin = soroban_sdk::Address::generate(&env);
        reg_client.init(&admin);

        // Register the test public key
        let pk = pubkey_bytes(&env);
        reg_client.add_attester(&pk);

        // Deploy verifier
        let ver_id = env.register(Verifier, ());
        let ver_client = VerifierClient::new(&env, &ver_id);
        ver_client.init(&reg_id);

        (env, ver_client, pk)
    }

    // ── Happy path ────────────────────────────────────────────────────────────

    #[test]
    fn valid_sig_returns_claim_hash() {
        let (env, client, pk) = setup();
        let att = make_attestation(&env, 0x01);
        let sig = sign_attestation(&env, &att);
        let returned = client.verify(&att, &pk, &sig);
        assert_eq!(returned, att.claim_hash);
    }

    // ── Bad signature ─────────────────────────────────────────────────────────

    #[test]
    #[should_panic]
    fn bad_sig_panics() {
        let (env, client, pk) = setup();
        let att = make_attestation(&env, 0x02);
        // All-zero signature — definitely invalid
        let bad_sig = BytesN::from_array(&env, &[0u8; 64]);
        client.verify(&att, &pk, &bad_sig);
    }

    // ── Replay attack ─────────────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "nonce already used")]
    fn replayed_nonce_panics() {
        let (env, client, pk) = setup();
        let att = make_attestation(&env, 0x03);
        let sig = sign_attestation(&env, &att);
        client.verify(&att, &pk, &sig); // first use: ok
        client.verify(&att, &pk, &sig); // replay: must panic
    }

    // ── Expired attestation ───────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "attestation expired")]
    fn expired_attestation_panics() {
        let (env, client, pk) = setup();
        // Move ledger past expiry
        env.ledger().with_mut(|l| l.timestamp = 3_000);
        let att = make_attestation(&env, 0x04);
        let sig = sign_attestation(&env, &att);
        client.verify(&att, &pk, &sig);
    }

    // ── Unregistered key ─────────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "unregistered attester key")]
    fn unregistered_key_panics() {
        let (env, client, _) = setup();
        let att = make_attestation(&env, 0x05);
        let unregistered = BytesN::from_array(&env, &[0xff; 32]);
        let sig = sign_attestation(&env, &att);
        client.verify(&att, &unregistered, &sig);
    }

    // ── False verdict ─────────────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "attestation verdict is false")]
    fn false_verdict_panics() {
        let (env, client, pk) = setup();
        let mut att = make_attestation(&env, 0x06);
        att.verdict = false;
        let sig = sign_attestation(&env, &att);
        client.verify(&att, &pk, &sig);
    }
}
