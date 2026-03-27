import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  env: {
    NEXT_PUBLIC_API_URL: "https://api-production-f3ea.up.railway.app",
  },
};

export default nextConfig;
