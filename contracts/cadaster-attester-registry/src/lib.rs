//! cadaster-attester-registry
//!
//! Stores the set of Ed25519 public keys that are authorised to sign
//! Cadaster attestations.  Only the admin may add or remove keys.
//!
//! Storage layout
//! ──────────────
//!   Instance: ADMIN  → Address
//!   Persistent: ATTESTER(pubkey_bytes_n32) → bool

#![no_std]

use soroban_sdk::{contract, contractimpl, contracttype, Address, BytesN, Env};

// ─── Storage keys ─────────────────────────────────────────────────────────────

#[contracttype]
pub enum DataKey {
    Admin,
    Attester(BytesN<32>),
}

// ─── Contract ─────────────────────────────────────────────────────────────────

#[contract]
pub struct AttesterRegistry;

#[contractimpl]
impl AttesterRegistry {
    // ── Initialisation ────────────────────────────────────────────────────────

    /// Must be called once immediately after deployment.
    pub fn init(env: Env, admin: Address) {
        if env.storage().instance().has(&DataKey::Admin) {
            panic!("already initialised");
        }
        env.storage().instance().set(&DataKey::Admin, &admin);
    }

    // ── Admin helpers ─────────────────────────────────────────────────────────

    fn require_admin(env: &Env) {
        let admin: Address = env
            .storage()
            .instance()
            .get(&DataKey::Admin)
            .expect("not initialised");
        admin.require_auth();
    }

    // ── Public interface ──────────────────────────────────────────────────────

    /// Authorise an Ed25519 public key.
    pub fn add_attester(env: Env, pubkey: BytesN<32>) {
        Self::require_admin(&env);
        env.storage()
            .persistent()
            .set(&DataKey::Attester(pubkey), &true);
    }

    /// Revoke an Ed25519 public key.
    pub fn remove_attester(env: Env, pubkey: BytesN<32>) {
        Self::require_admin(&env);
        env.storage()
            .persistent()
            .remove(&DataKey::Attester(pubkey));
    }

    /// Returns `true` if the key is currently authorised.
    pub fn is_attester(env: Env, pubkey: BytesN<32>) -> bool {
        env.storage()
            .persistent()
            .get(&DataKey::Attester(pubkey))
            .unwrap_or(false)
    }

    /// Return the current admin address.
    pub fn admin(env: Env) -> Address {
        env.storage()
            .instance()
            .get(&DataKey::Admin)
            .expect("not initialised")
    }

    /// Transfer admin role; old admin must authorise.
    pub fn transfer_admin(env: Env, new_admin: Address) {
        Self::require_admin(&env);
        env.storage().instance().set(&DataKey::Admin, &new_admin);
    }
}

// ─── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use soroban_sdk::{testutils::Address as _, Env};

    fn setup() -> (Env, AttesterRegistryClient<'static>) {
        let env = Env::default();
        env.mock_all_auths();
        let contract_id = env.register(AttesterRegistry, ());
        let client = AttesterRegistryClient::new(&env, &contract_id);
        (env, client)
    }

    #[test]
    fn add_and_query() {
        let (env, client) = setup();
        let admin = Address::generate(&env);
        client.init(&admin);

        let key: BytesN<32> = BytesN::from_array(&env, &[1u8; 32]);
        assert!(!client.is_attester(&key));

        client.add_attester(&key);
        assert!(client.is_attester(&key));
    }

    #[test]
    fn remove_attester() {
        let (env, client) = setup();
        let admin = Address::generate(&env);
        client.init(&admin);

        let key: BytesN<32> = BytesN::from_array(&env, &[2u8; 32]);
        client.add_attester(&key);
        assert!(client.is_attester(&key));

        client.remove_attester(&key);
        assert!(!client.is_attester(&key));
    }

    #[test]
    #[should_panic(expected = "already initialised")]
    fn double_init_panics() {
        let (env, client) = setup();
        let admin = Address::generate(&env);
        client.init(&admin);
        client.init(&admin); // should panic
    }

    #[test]
    fn transfer_admin_works() {
        let (env, client) = setup();
        let admin = Address::generate(&env);
        let new_admin = Address::generate(&env);
        client.init(&admin);
        client.transfer_admin(&new_admin);
        assert_eq!(client.admin(), new_admin);
    }
}
