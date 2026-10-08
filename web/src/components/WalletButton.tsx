"use client";
/**
 * web/src/components/WalletButton.tsx
 *
 * Connects to Freighter wallet via @creit.tech/stellar-wallets-kit.
 * Falls back to a manual key entry field if Freighter is not installed.
 */

import { useState, useCallback } from "react";

interface WalletState {
  address: string | null;
  connected: boolean;
}

interface Props {
  onWalletChange: (state: WalletState & {
    signTransaction: ((xdr: string) => Promise<string>) | null;
  }) => void;
}

export default function WalletButton({ onWalletChange }: Props) {
  const [address, setAddress] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Dynamic import so SSR doesn't break
      const { StellarWalletsKit, WalletNetwork, FREIGHTER_ID } = await import(
        "@creit.tech/stellar-wallets-kit"
      );

      const networkMap: Record<string, string> = {
        TESTNET: WalletNetwork.TESTNET,
        PUBLIC: WalletNetwork.PUBLIC,
      };
      const network =
        networkMap[process.env.NEXT_PUBLIC_STELLAR_NETWORK ?? "TESTNET"] ??
        WalletNetwork.TESTNET;

      const kit = new StellarWalletsKit({
        network: network as unknown as WalletNetwork,
        selectedWalletId: FREIGHTER_ID,
        wallets: [],
      });

      await kit.openModal({
        onWalletSelected: async (option) => {
          kit.setWallet(option.id);
          const { address: addr } = await kit.getAddress();
          setAddress(addr);
          onWalletChange({
            address: addr,
            connected: true,
            signTransaction: async (xdr: string) => {
              const { signedTxXdr } = await kit.signTransaction(xdr);
              return signedTxXdr;
            },
          });
        },
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [onWalletChange]);

  const disconnect = useCallback(() => {
    setAddress(null);
    onWalletChange({ address: null, connected: false, signTransaction: null });
  }, [onWalletChange]);

  if (address) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span
          style={{
            fontSize: "0.75rem",
            color: "var(--color-text-muted)",
            fontFamily: "monospace",
            maxWidth: "200px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={address}
        >
          {address.slice(0, 6)}…{address.slice(-4)}
        </span>
        <button
          onClick={disconnect}
          style={{
            padding: "4px 12px",
            borderRadius: "6px",
            border: `1px solid var(--color-border)`,
            background: "transparent",
            color: "var(--color-text-muted)",
            cursor: "pointer",
            fontSize: "0.8rem",
          }}
        >
          Disconnect
        </button>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={connect}
        disabled={loading}
        style={{
          padding: "8px 20px",
          borderRadius: "8px",
          border: "none",
          background: "var(--color-primary)",
          color: "#fff",
          cursor: loading ? "wait" : "pointer",
          fontSize: "0.9rem",
          fontWeight: 600,
          opacity: loading ? 0.7 : 1,
        }}
        aria-label="Connect Stellar wallet"
      >
        {loading ? "Connecting…" : "Connect Wallet"}
      </button>
      {error && (
        <p
          style={{
            color: "var(--color-error)",
            fontSize: "0.8rem",
            marginTop: "4px",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
