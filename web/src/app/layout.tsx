import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cadaster — Geo-Verification Oracle",
  description:
    "Geo-verification oracle for RWA tokenization on Stellar. An agent checks claimed coordinates against satellite data and signs an attestation before minting.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
