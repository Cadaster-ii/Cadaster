/**
 * web/src/lib/agentApi.ts
 *
 * Typed client for the Cadaster agent REST API.
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_AGENT_URL ?? "http://localhost:8000";

// ── Request types ─────────────────────────────────────────────────────────────

export interface LandClaim {
  polygon: GeoJSONPolygon;
  country_code: string; // ISO 3166-1 alpha-2, lower-case
  asset_type: number;   // 1 = land parcel
  description?: string;
}

export interface GeoJSONPolygon {
  type: "Polygon";
  coordinates: [number, number][][];
}

// ── Response types ─────────────────────────────────────────────────────────────

export interface CheckDetail {
  name: string;
  passed: boolean;
  score: number;
  reason: string;
  evidence: Record<string, unknown>;
}

export interface VerifyResponse {
  verdict: boolean;
  confidence_score: number;
  checks: CheckDetail[];
  claim_hash: string;
  message: string;
}

export interface AttestationFields {
  claim_hash: string;
  asset_type: number;
  verdict: boolean;
  score: number;
  issued_at: number;
  expiry: number;
  nonce: string;
}

export interface AttestResponse {
  verdict: boolean;
  confidence_score: number;
  claim_hash: string;
  attestation: AttestationFields;
  pubkey_hex: string;
  signature_hex: string;
  checks: CheckDetail[];
  message: string;
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(
      typeof detail.detail === "string"
        ? detail.detail
        : detail.detail?.message ?? `HTTP ${res.status}`
    );
  }

  return res.json() as Promise<T>;
}

export const agentApi = {
  verify: (claim: LandClaim) => post<VerifyResponse>("/verify", claim),
  attest: (claim: LandClaim) => post<AttestResponse>("/attest", claim),
};
