"use client";
/**
 * web/src/components/ChecksPanel.tsx
 *
 * Displays the list of geo-verification checks and their outcomes.
 */

import type { CheckDetail } from "@/lib/agentApi";

interface Props {
  checks: CheckDetail[];
  score: number;
  verdict: boolean;
}

export default function ChecksPanel({ checks, score, verdict }: Props) {
  return (
    <div
      style={{
        border: `1px solid var(--color-border)`,
        borderRadius: "8px",
        overflow: "hidden",
      }}
      role="region"
      aria-label="Verification results"
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 16px",
          backgroundColor: verdict
            ? "var(--color-success)"
            : "var(--color-error)",
          color: "#fff",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontWeight: 600, fontSize: "1rem" }}>
          {verdict ? "✓ Verification passed" : "✗ Verification failed"}
        </span>
        <span
          style={{
            background: "rgba(255,255,255,0.2)",
            borderRadius: "20px",
            padding: "2px 10px",
            fontSize: "0.85rem",
          }}
        >
          Score: {score}/100
        </span>
      </div>

      {/* Check rows */}
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {checks.map((check, i) => (
          <li
            key={check.name}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: "10px",
              padding: "10px 16px",
              borderBottom:
                i < checks.length - 1
                  ? `1px solid var(--color-border)`
                  : undefined,
              backgroundColor: check.passed
                ? "transparent"
                : "rgba(220, 38, 38, 0.04)",
            }}
          >
            {/* Icon */}
            <span
              style={{
                fontSize: "1rem",
                marginTop: "1px",
                color: check.passed
                  ? "var(--color-success)"
                  : "var(--color-error)",
                flexShrink: 0,
              }}
              aria-hidden="true"
            >
              {check.passed ? "✓" : "✗"}
            </span>

            {/* Details */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontWeight: 500,
                  fontSize: "0.875rem",
                  color: "var(--color-text)",
                }}
              >
                {check.name.replace(/_/g, " ")}
              </div>
              {!check.passed && check.reason && (
                <div
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--color-error)",
                    marginTop: "2px",
                  }}
                >
                  {check.reason}
                </div>
              )}
            </div>

            {/* Score badge */}
            <span
              style={{
                fontSize: "0.75rem",
                color: "var(--color-text-muted)",
                flexShrink: 0,
              }}
            >
              {check.score}/100
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
