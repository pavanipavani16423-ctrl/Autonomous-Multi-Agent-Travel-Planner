import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Pin the workspace root so Turbopack does not guess from lockfiles higher up the tree.
  turbopack: { root: process.cwd() },
  images: {
    // Destination photography comes from Wikipedia's REST summaries, which serve from both hosts.
    remotePatterns: [
      { protocol: "https", hostname: "upload.wikimedia.org" },
      { protocol: "https", hostname: "thumb.wikimedia.org" },
    ],
  },
};

export default nextConfig;
