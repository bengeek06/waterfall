import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  allowedDevOrigins: (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "localhost,127.0.0.1")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean),
};

export default nextConfig;
