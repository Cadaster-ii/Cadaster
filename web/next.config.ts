import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Leaflet uses browser globals — keep it client-only
  webpack: (config) => {
    config.resolve.fallback = { fs: false, net: false, tls: false };
    return config;
  },
};

export default nextConfig;
