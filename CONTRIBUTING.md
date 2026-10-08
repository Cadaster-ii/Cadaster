# Contributing to Cadaster

Thank you for your interest in contributing! This document covers how to set up the project locally, branch conventions, testing, and the review process.

---

## Local setup

### Prerequisites

| Tool | Version |
|---|---|
| Rust | 1.81+ (stable) |
| `wasm32-unknown-unknown` target | `rustup target add wasm32-unknown-unknown` |
| `stellar` CLI | [install guide](https://developers.stellar.org/docs/tools/stellar-cli) |
| Python | 3.11+ |
| Node.js | 20+ |
| PostgreSQL + PostGIS | 15+ (optional — for overlap checks) |

### 1. Contracts

```bash
cd contracts
cargo test --features testutils
# Expect: 17 tests pass across 3 crates
```

To build WASM for deployment:

```bash
cargo build --release --target wasm32-unknown-unknown
```

### 2. Agent

```bash
cd agent
cp ../.env.example .env
# Edit .env — see below for required keys

pip install -r requirements.txt
python -m pytest           # 15 tests
uvicorn agent.main:app --reload
```

### 3. Frontend

```bash
cd web
cp .env.local.example .env.local
npm install
npm run dev
npm run type-check         # tsc --noEmit
```

---

## Environment variables

Copy `.env.example` to `.env` at the repo root (for the agent) and fill in values. The only required key for local dev without real satellite data is:

```
ATTESTER_PRIVATE_KEY_HEX   32 random bytes as hex (openssl rand -hex 32)
```

Land-cover checks are skipped gracefully if Sentinel Hub credentials are absent; the agent will return `available=false` for that check and refuse to sign.

---

## Branch and PR conventions

| Branch prefix | Purpose |
|---|---|
| `feat/` | New feature |
| `fix/` | Bug fix |
| `chore/` | Tooling, deps, CI |
| `docs/` | Documentation only |
| `refactor/` | Code quality, no behaviour change |

**Rules:**

- Branch off `main`. Do not push directly to `main`.
- Keep commits atomic and their messages in imperative mood: `Add overlap check`, not `Added overlap check`.
- Squash fixup commits before requesting review.
- PR titles must be ≤ 70 characters. Put detail in the description.
- Every PR needs a passing CI build before merge.
- Every PR needs **at least one approving review** from a maintainer.

---

## Running tests

### Rust

```bash
cd contracts
cargo test --features testutils
```

All three crates are tested in one run. Tests cover valid paths and all five failure modes (bad sig, replay, expiry, unregistered key, false verdict).

### Python

```bash
cd ..   # repo root
python -m pytest
```

Uses `pytest.ini` at the repo root; tests live in `agent/tests/`. Network calls are not made by unit tests — providers are tested via integration tests (not included in CI by default, requires credentials).

### TypeScript

```bash
cd web
npm run type-check
npm run lint
```

---

## Issue labels

| Label | Meaning |
|---|---|
| `complexity: trivial` | < 30 min, isolated change, no design decisions |
| `complexity: medium` | Requires understanding one subsystem, moderate testing |
| `complexity: high` | Cross-cutting, design discussion needed, substantial testing |
| `good first issue` | Well-scoped, self-contained — ideal for new contributors |
| `bug` | Something is broken |
| `enhancement` | New capability |
| `security` | Security-sensitive — assign a maintainer immediately |

---

## Code style

- **Rust**: `cargo fmt` + `cargo clippy -- -D warnings` before committing.
- **Python**: `ruff format` + `ruff check` (configured in `pyproject.toml`).
- **TypeScript/TSX**: `next lint` (ESLint with the Next.js ruleset).

---

## Security

Report security vulnerabilities privately to `security@example.org` (replace with your actual address). Do not open a public issue for security bugs.

---

## Code of Conduct

All contributors are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
