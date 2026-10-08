//! cadaster-token  (SEP-41 compatible land-parcel token, soroban-sdk 29)
//!
//! # Architecture
//!
//! ```text
//!   mint(to, attestation, pubkey, sig)
//!        │
//!        ├─ cross-contract call → cadaster-verifier.verify(...)
//!        │        │
//!        │        └─ cross-contract call → cadaster-attester-registry.is_attester(...)
//!        │
//!        └─ on success: update balances, record claim_hash, emit event
//! ```
//!
//! The token follows SEP-41 naming conventions.  One "unit" (1 token) is minted
//! per successful attestation.  Land parcel tokens are non-fungible in spirit —
//! the `claim_hash` differentiates parcels — but the standard SEP-41 balance/
//! transfer interface lets wallets and explorers handle them.
//!
//! Storage layout
//! ──────────────
//!   Instance:
//!     Admin    → Address
//!     Verifier → Address
//!     TotalSupply → i128
//!   Persistent:
//!     Balance(Address)        → i128
//!     ParcelOwner(BytesN<32>) → Address   (claim_hash → owner)

#![no_std]

use soroban_sdk::{
    contract, contractimpl, contracttype, symbol_short, Address, BytesN, Env, String,
};

use cadaster_verifier::{attestation::Attestation, VerifierClient};

// ─── Storage keys ─────────────────────────────────────────────────────────────

#[contracttype]
pub enum DataKey {
    Admin,
    Verifier,
    Balance(Address),
    TotalSupply,
    /// Maps claim_hash → owner address (land-parcel registry)
    ParcelOwner(BytesN<32>),
}

// ─── Contract ─────────────────────────────────────────────────────────────────

#[contract]
pub struct CadasterToken;

#[contractimpl]
impl CadasterToken {
    // ── Initialisation ────────────────────────────────────────────────────────

    /// Deploy and initialise the token.
    /// `verifier` is the address of the deployed cadaster-verifier contract.
    pub fn init(env: Env, admin: Address, verifier: Address) {
        if env.storage().instance().has(&DataKey::Admin) {
            panic!("already initialised");
        }
        env.storage().instance().set(&DataKey::Admin, &admin);
        env.storage().instance().set(&DataKey::Verifier, &verifier);
        env.storage()
            .instance()
            .set(&DataKey::TotalSupply, &0i128);
    }

    // ── SEP-41 metadata ───────────────────────────────────────────────────────

    pub fn name(env: Env) -> String {
        String::from_str(&env, "Cadaster Land Parcel")
    }

    pub fn symbol(env: Env) -> String {
        String::from_str(&env, "CDSTR")
    }

    pub fn decimals(_env: Env) -> u32 {
        0 // integer tokens — one per parcel
    }

    // ── SEP-41 balances ───────────────────────────────────────────────────────

    pub fn balance(env: Env, id: Address) -> i128 {
        env.storage()
            .persistent()
            .get(&DataKey::Balance(id))
            .unwrap_or(0)
    }

    pub fn total_supply(env: Env) -> i128 {
        env.storage()
            .instance()
            .get(&DataKey::TotalSupply)
            .unwrap_or(0)
    }

    // ── SEP-41 transfer ───────────────────────────────────────────────────────

    /// Standard token transfer.
    pub fn transfer(env: Env, from: Address, to: Address, amount: i128) {
        from.require_auth();
        if amount <= 0 {
            panic!("amount must be positive");
        }
        let from_bal = Self::balance(env.clone(), from.clone());
        if from_bal < amount {
            panic!("insufficient balance");
        }
        let to_bal = Self::balance(env.clone(), to.clone());
        env.storage()
            .persistent()
            .set(&DataKey::Balance(from.clone()), &(from_bal - amount));
        env.storage()
            .persistent()
            .set(&DataKey::Balance(to.clone()), &(to_bal + amount));
        env.events().publish(
            (symbol_short!("transfer"), from),
            (to, amount),
        );
    }

    // ── Cadaster-specific: mint via attestation ───────────────────────────────

    /// Gate-kept mint: calls cadaster-verifier before touching balances.
    ///
    /// `to`          – recipient address (the asset owner).
    /// `attestation` – the Attestation struct built by the off-chain agent.
    /// `pubkey`      – Ed25519 public key (32 bytes) of the attester.
    /// `signature`   – Ed25519 signature (64 bytes) over xdr_serialize(attestation).
    pub fn mint(
        env: Env,
        to: Address,
        attestation: Attestation,
        pubkey: BytesN<32>,
        signature: BytesN<64>,
    ) {
        // Cross-contract call to the verifier — will panic on any failure.
        let verifier: Address = env
            .storage()
            .instance()
            .get(&DataKey::Verifier)
            .expect("token not initialised");

        let ver_client = VerifierClient::new(&env, &verifier);
        let claim_hash: BytesN<32> = ver_client.verify(&attestation, &pubkey, &signature);

        // Ensure this parcel hasn't already been minted (one token per parcel).
        let parcel_key = DataKey::ParcelOwner(claim_hash.clone());
        if env.storage().persistent().has(&parcel_key) {
            panic!("parcel already minted");
        }

        // Credit the recipient.
        let new_bal = Self::balance(env.clone(), to.clone()) + 1;
        env.storage()
            .persistent()
            .set(&DataKey::Balance(to.clone()), &new_bal);

        // Record parcel → owner.
        env.storage().persistent().set(&parcel_key, &to);

        // Update total supply.
        let supply = Self::total_supply(env.clone()) + 1;
        env.storage()
            .instance()
            .set(&DataKey::TotalSupply, &supply);

        // Emit mint event.
        env.events().publish(
            (symbol_short!("mint"), to.clone()),
            (claim_hash.clone(), attestation.score),
        );
    }

    // ── Parcel query ──────────────────────────────────────────────────────────

    /// Return the current owner of a land parcel given its claim_hash.
    pub fn parcel_owner(env: Env, claim_hash: BytesN<32>) -> Option<Address> {
        env.storage()
            .persistent()
            .get(&DataKey::ParcelOwner(claim_hash))
    }
}

// ─── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    extern crate std;

    use super::*;
    use cadaster_attester_registry::{AttesterRegistry, AttesterRegistryClient};
    use cadaster_verifier::{attestation::Attestation, Verifier, VerifierClient};
    use soroban_sdk::{
        testutils::{Address as _, Ledger},
        xdr::ToXdr,
        BytesN, Env,
    };

    // Same deterministic test key as in cadaster-verifier tests
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

    fn sign_attestation(env: &Env, attestation: &Attestation) -> BytesN<64> {
        use ed25519_dalek::Signer;
        let serialized = attestation.clone().to_xdr(env);
        let mut buf = std::vec![0u8; serialized.len() as usize];
        serialized.copy_into_slice(&mut buf);
        let sig = signing_key().sign(&buf);
        BytesN::from_array(env, &sig.to_bytes())
    }

    fn make_attestation(env: &Env, nonce_byte: u8) -> Attestation {
        Attestation {
            claim_hash: BytesN::from_array(env, &[0xcd; 32]),
            asset_type: 1,
            verdict: true,
            score: 88,
            issued_at: 1_000,
            expiry: 2_000,
            nonce: BytesN::from_array(env, &[nonce_byte; 32]),
        }
    }

    /// Deploy registry + verifier + token, register test key, return clients.
    fn setup() -> (Env, CadasterTokenClient<'static>, BytesN<32>) {
        let env = Env::default();
        env.mock_all_auths();
        env.ledger().with_mut(|l| l.timestamp = 1_500);

        let admin = soroban_sdk::Address::generate(&env);

        // Registry
        let reg_id = env.register(AttesterRegistry, ());
        let reg_client = AttesterRegistryClient::new(&env, &reg_id);
        reg_client.init(&admin);
        let pk = pubkey_bytes(&env);
        reg_client.add_attester(&pk);

        // Verifier
        let ver_id = env.register(Verifier, ());
        let ver_client = VerifierClient::new(&env, &ver_id);
        ver_client.init(&reg_id);

        // Token
        let tok_id = env.register(CadasterToken, ());
        let tok_client = CadasterTokenClient::new(&env, &tok_id);
        tok_client.init(&admin, &ver_id);

        (env, tok_client, pk)
    }

    // ── Happy path ────────────────────────────────────────────────────────────

    #[test]
    fn valid_attestation_mints_token() {
        let (env, client, pk) = setup();
        let recipient = soroban_sdk::Address::generate(&env);
        let att = make_attestation(&env, 0xA1);
        let sig = sign_attestation(&env, &att);

        assert_eq!(client.balance(&recipient), 0);
        client.mint(&recipient, &att, &pk, &sig);
        assert_eq!(client.balance(&recipient), 1);
        assert_eq!(client.total_supply(), 1);

        let owner = client.parcel_owner(&att.claim_hash).unwrap();
        assert_eq!(owner, recipient);
    }

    // ── Bad signature ─────────────────────────────────────────────────────────

    #[test]
    #[should_panic]
    fn bad_sig_blocks_mint() {
        let (env, client, pk) = setup();
        let recipient = soroban_sdk::Address::generate(&env);
        let att = make_attestation(&env, 0xA2);
        let bad_sig = BytesN::from_array(&env, &[0u8; 64]);
        client.mint(&recipient, &att, &pk, &bad_sig);
    }

    // ── Replay ────────────────────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "nonce already used")]
    fn replay_blocks_second_mint() {
        let (env, client, pk) = setup();
        let recipient = soroban_sdk::Address::generate(&env);
        let att = make_attestation(&env, 0xA3);
        let sig = sign_attestation(&env, &att);
        client.mint(&recipient, &att, &pk, &sig);
        client.mint(&recipient, &att, &pk, &sig); // replay
    }

    // ── Expired ───────────────────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "attestation expired")]
    fn expired_attestation_blocks_mint() {
        let (env, client, pk) = setup();
        env.ledger().with_mut(|l| l.timestamp = 5_000);
        let recipient = soroban_sdk::Address::generate(&env);
        let att = make_attestation(&env, 0xA4);
        let sig = sign_attestation(&env, &att);
        client.mint(&recipient, &att, &pk, &sig);
    }

    // ── Unregistered key ─────────────────────────────────────────────────────

    #[test]
    #[should_panic(expected = "unregistered attester key")]
    fn unregistered_key_blocks_mint() {
        let (env, client, _) = setup();
        let recipient = soroban_sdk::Address::generate(&env);
        let att = make_attestation(&env, 0xA5);
        let bad_key = BytesN::from_array(&env, &[0xEE; 32]);
        let sig = sign_attestation(&env, &att);
        client.mint(&recipient, &att, &bad_key, &sig);
    }

    // ── Transfer ─────────────────────────────────────────────────────────────

    #[test]
    fn transfer_works() {
        let (env, client, pk) = setup();
        let alice = soroban_sdk::Address::generate(&env);
        let bob = soroban_sdk::Address::generate(&env);
        let att = make_attestation(&env, 0xA6);
        let sig = sign_attestation(&env, &att);
        client.mint(&alice, &att, &pk, &sig);

        client.transfer(&alice, &bob, &1i128);
        assert_eq!(client.balance(&alice), 0);
        assert_eq!(client.balance(&bob), 1);
    }

    // ── SEP-41 metadata ───────────────────────────────────────────────────────

    #[test]
    fn metadata_is_correct() {
        let (env, client, _) = setup();
        assert_eq!(
            client.name(),
            soroban_sdk::String::from_str(&env, "Cadaster Land Parcel")
        );
        assert_eq!(
            client.symbol(),
            soroban_sdk::String::from_str(&env, "CDSTR")
        );
        assert_eq!(client.decimals(), 0);
    }
}
