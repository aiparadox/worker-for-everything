import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server output used by frontend/Dockerfile (FEAT-20261010-1202).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
