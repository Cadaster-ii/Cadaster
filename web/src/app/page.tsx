"use client";
/**
 * web/src/app/page.tsx
 *
 * Cadaster — single-page land parcel verification and minting demo.
 *
 * Flow:
 *   1. Draw a polygon on the map (or paste GeoJSON)
 *   2. Fill in country code + optional description
 *   3. Click "Verify" → call agent /verify, show check results
 *   4. If verified, connect Freighter wallet
 *   5. Click "Attest + Mint" → call agent /attest, submit mint() to chain
 */

import { useState, useCallback, Suspense } from "react";
import dynamic from "next/dynamic";
import WalletButton from "@/components/WalletButton";
import ChecksPanel from "@/components/ChecksPanel";
import { agentApi, type GeoJSONPolygon, type VerifyResponse, type AttestResponse } from "@/lib/agentApi";
import { mintParcel } from "@/lib/stellar";

// Leaflet must be loaded client-side only
const MapDrawer = dynamic(() => import("@/components/MapDrawer"), {
  ssr: false,
  loading: () => (
    <div
      style={{
        height: "400px",
        borderRadius: "8px",
        background: "var(--color-surface-dark)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--color-text-muted)",
        fontSize: "0.875rem",
      }}
    >
      Loading map…
    </div>
  ),
});

// ── Types ─────────────────────────────────────────────────────────────────────

type Step = "idle" | "verifying" | "verified" | "attesting" | "minted" | "error";

interface WalletState {
  address: string | null;
  signTransaction: ((xdr: string) => Promise<string>) | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
}) {
  const bg =
    variant === "primary"
      ? "var(--color-primary)"
      : variant === "danger"
      ? "var(--color-error)"
      : "transparent";
  const fg = variant === "secondary" ? "var(--color-text)" : "#fff";
  const bd =
    variant === "secondary" ? `1px solid var(--color-border)` : "none";

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "10px 24px",
        borderRadius: "8px",
        border: bd,
        background: disabled ? "var(--color-border)" : bg,
        color: disabled ? "var(--color-text-muted)" : fg,
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: "0.9rem",
        fontWeight: 600,
        transition: "opacity 0.15s",
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "var(--color-surface)",
        border: `1px solid var(--color-border)`,
        borderRadius: "12px",
        padding: "20px 24px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function Label({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label
      htmlFor={htmlFor}
      style={{
        display: "block",
        fontSize: "0.8rem",
        fontWeight: 600,
        color: "var(--color-text-muted)",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        marginBottom: "6px",
      }}
    >
      {children}
    </label>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Home() {
  const [polygon, setPolygon] = useState<GeoJSONPolygon | null>(null);
  const [pastedJson, setPastedJson] = useState("");
  const [countryCode, setCountryCode] = useState("");
  const [description, setDescription] = useState("");

  const [step, setStep] = useState<Step>("idle");
  const [verifyResult, setVerifyResult] = useState<VerifyResponse | null>(null);
  const [attestResult, setAttestResult] = useState<AttestResponse | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [wallet, setWallet] = useState<WalletState>({
    address: null,
    signTransaction: null,
  });

  // ── Resolve polygon ────────────────────────────────────────────────────────
  const resolvedPolygon = useCallback((): GeoJSONPolygon | null => {
    if (polygon) return polygon;
    if (pastedJson.trim()) {
      try {
        const parsed = JSON.parse(pastedJson);
        if (parsed.type === "Polygon") return parsed as GeoJSONPolygon;
        if (parsed.type === "Feature" && parsed.geometry?.type === "Polygon")
          return parsed.geometry as GeoJSONPolygon;
      } catch {
        /* handled in submit */
      }
    }
    return null;
  }, [polygon, pastedJson]);

  // ── Verify ─────────────────────────────────────────────────────────────────
  const handleVerify = async () => {
    const poly = resolvedPolygon();
    if (!poly) {
      setErrorMsg("Please draw a polygon or paste GeoJSON first.");
      return;
    }
    if (!countryCode || countryCode.length !== 2) {
      setErrorMsg("Enter a 2-letter ISO country code (e.g. us, fr, br).");
      return;
    }

    setStep("verifying");
    setErrorMsg(null);
    setVerifyResult(null);
    setAttestResult(null);
    setTxHash(null);

    try {
      const result = await agentApi.verify({
        polygon: poly,
        country_code: countryCode.toLowerCase(),
        asset_type: 1,
        description,
      });
      setVerifyResult(result);
      setStep("verified");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setStep("error");
    }
  };

  // ── Attest + Mint ──────────────────────────────────────────────────────────
  const handleMint = async () => {
    const poly = resolvedPolygon();
    if (!poly || !wallet.address || !wallet.signTransaction) return;

    setStep("attesting");
    setErrorMsg(null);

    try {
      // 1. Get a signed attestation from the agent
      const att = await agentApi.attest({
        polygon: poly,
        country_code: countryCode.toLowerCase(),
        asset_type: 1,
        description,
      });
      setAttestResult(att);

      // 2. Submit mint() transaction to Soroban via Freighter
      const { txHash: hash } = await mintParcel({
        walletAddress: wallet.address,
        signTransaction: wallet.signTransaction,
        attestation: att.attestation,
        pubkey_hex: att.pubkey_hex,
        signature_hex: att.signature_hex,
      });

      setTxHash(hash);
      setStep("minted");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setStep("error");
    }
  };

  const reset = () => {
    setStep("idle");
    setVerifyResult(null);
    setAttestResult(null);
    setTxHash(null);
    setErrorMsg(null);
    setPolygon(null);
    setPastedJson("");
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <main
      style={{
        maxWidth: "800px",
        margin: "0 auto",
        padding: "32px 16px 64px",
      }}
    >
      {/* Header */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "32px",
        }}
      >
        <div>
          <h1
            style={{
              margin: 0,
              fontSize: "1.5rem",
              fontWeight: 700,
              color: "var(--color-primary)",
              letterSpacing: "-0.02em",
            }}
          >
            Cadaster
          </h1>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: "0.85rem",
              color: "var(--color-text-muted)",
            }}
          >
            Geo-verification oracle for land RWA tokenization on Stellar
          </p>
        </div>
        <WalletButton
          onWalletChange={({ address, signTransaction }) =>
            setWallet({ address, signTransaction })
          }
        />
      </header>

      {/* Step 1: Map */}
      <Card style={{ marginBottom: "20px" }}>
        <h2
          style={{
            margin: "0 0 12px",
            fontSize: "1rem",
            fontWeight: 600,
            color: "var(--color-text)",
          }}
        >
          1. Define the land parcel
        </h2>
        <p
          style={{
            margin: "0 0 12px",
            fontSize: "0.85rem",
            color: "var(--color-text-muted)",
          }}
        >
          Draw a polygon on the map using the polygon tool (top-left corner),
          or paste a GeoJSON Polygon geometry below.
        </p>

        <Suspense fallback={null}>
          <MapDrawer onPolygonChange={setPolygon} />
        </Suspense>

        <div style={{ marginTop: "12px" }}>
          <Label htmlFor="geojson-paste">Or paste GeoJSON Polygon</Label>
          <textarea
            id="geojson-paste"
            value={pastedJson}
            onChange={(e) => setPastedJson(e.target.value)}
            placeholder='{"type":"Polygon","coordinates":[[[lon,lat],...]]}'
            rows={3}
            style={{
              width: "100%",
              fontFamily: "monospace",
              fontSize: "0.8rem",
              padding: "8px 12px",
              borderRadius: "6px",
              border: `1px solid var(--color-border)`,
              background: "var(--color-surface-dark)",
              color: "var(--color-text)",
              resize: "vertical",
            }}
          />
        </div>

        {polygon && (
          <p
            style={{
              margin: "8px 0 0",
              fontSize: "0.8rem",
              color: "var(--color-success)",
            }}
          >
            ✓ Polygon drawn ({polygon.coordinates[0].length - 1} vertices)
          </p>
        )}
      </Card>

      {/* Step 2: Metadata */}
      <Card style={{ marginBottom: "20px" }}>
        <h2
          style={{
            margin: "0 0 12px",
            fontSize: "1rem",
            fontWeight: 600,
          }}
        >
          2. Claim metadata
        </h2>

        <div style={{ display: "grid", gap: "16px", gridTemplateColumns: "1fr 2fr" }}>
          <div>
            <Label htmlFor="country-code">Country code *</Label>
            <input
              id="country-code"
              type="text"
              value={countryCode}
              onChange={(e) => setCountryCode(e.target.value.toLowerCase())}
              placeholder="e.g. us"
              maxLength={2}
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: "6px",
                border: `1px solid var(--color-border)`,
                background: "var(--color-surface-dark)",
                color: "var(--color-text)",
                fontSize: "0.9rem",
              }}
              aria-required="true"
            />
          </div>
          <div>
            <Label htmlFor="description">Description (optional)</Label>
            <input
              id="description"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Farm land, northern plot"
              maxLength={512}
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: "6px",
                border: `1px solid var(--color-border)`,
                background: "var(--color-surface-dark)",
                color: "var(--color-text)",
                fontSize: "0.9rem",
              }}
            />
          </div>
        </div>
      </Card>

      {/* Actions */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "24px", flexWrap: "wrap" }}>
        <Button
          onClick={handleVerify}
          disabled={step === "verifying" || step === "attesting"}
          aria-label="Run verification checks"
        >
          {step === "verifying" ? "Verifying…" : "Verify"}
        </Button>

        {verifyResult?.verdict && (
          <Button
            onClick={handleMint}
            disabled={!wallet.address || step === "attesting" || step === "minted"}
            variant="primary"
            aria-label="Request attestation and mint token"
          >
            {step === "attesting"
              ? "Attesting…"
              : !wallet.address
              ? "Connect wallet to mint"
              : "Attest + Mint"}
          </Button>
        )}

        {(step === "minted" || step === "error") && (
          <Button onClick={reset} variant="secondary">
            Start over
          </Button>
        )}
      </div>

      {/* Error */}
      {errorMsg && (
        <div
          role="alert"
          style={{
            padding: "12px 16px",
            borderRadius: "8px",
            background: "rgba(220, 38, 38, 0.08)",
            border: `1px solid var(--color-error)`,
            color: "var(--color-error)",
            fontSize: "0.875rem",
            marginBottom: "20px",
          }}
        >
          <strong>Error: </strong>
          {errorMsg}
        </div>
      )}

      {/* Verification results */}
      {verifyResult && (
        <div style={{ marginBottom: "20px" }}>
          <h2
            style={{
              margin: "0 0 12px",
              fontSize: "1rem",
              fontWeight: 600,
            }}
          >
            3. Verification results
          </h2>
          <ChecksPanel
            checks={verifyResult.checks}
            score={verifyResult.confidence_score}
            verdict={verifyResult.verdict}
          />
          <p
            style={{
              marginTop: "8px",
              fontSize: "0.8rem",
              color: "var(--color-text-muted)",
              fontFamily: "monospace",
            }}
          >
            Claim hash: {verifyResult.claim_hash}
          </p>
        </div>
      )}

      {/* Mint success */}
      {step === "minted" && txHash && (
        <Card
          style={{
            borderColor: "var(--color-success)",
            background: "rgba(22, 163, 74, 0.04)",
          }}
        >
          <h2
            style={{
              margin: "0 0 8px",
              fontSize: "1rem",
              fontWeight: 700,
              color: "var(--color-success)",
            }}
          >
            ✓ Land parcel token minted!
          </h2>
          <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
            Transaction hash:
          </p>
          <a
            href={`https://stellar.expert/explorer/testnet/tx/${txHash}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontFamily: "monospace",
              fontSize: "0.8rem",
              color: "var(--color-primary)",
              wordBreak: "break-all",
            }}
          >
            {txHash}
          </a>
          {attestResult && (
            <p
              style={{
                marginTop: "12px",
                fontSize: "0.8rem",
                color: "var(--color-text-muted)",
              }}
            >
              Attestation score: {attestResult.confidence_score}/100 · Signed by:{" "}
              <code style={{ fontSize: "0.75rem" }}>
                {attestResult.pubkey_hex.slice(0, 16)}…
              </code>
            </p>
          )}
        </Card>
      )}

      {/* Footer */}
      <footer
        style={{
          marginTop: "48px",
          textAlign: "center",
          fontSize: "0.75rem",
          color: "var(--color-text-muted)",
        }}
      >
        Cadaster · MIT License ·{" "}
        <a
          href="https://github.com/cadaster-project/cadaster"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--color-primary)" }}
        >
          GitHub
        </a>
      </footer>
    </main>
  );
}
