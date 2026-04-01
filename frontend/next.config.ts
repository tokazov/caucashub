import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  turbopack: undefined,
  env: {
    NEXT_PUBLIC_API_URL: "https://api-production-f3ea.up.railway.app",
  },
  generateBuildId: async () => {
    return `build-${Date.now()}`;
  },
};

export default nextConfig;
