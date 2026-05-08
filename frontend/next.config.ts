import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // NOTE: When deploying to Vercel, you MUST set the BACKEND_URL environment variable
    // to your deployed FastAPI backend URL (e.g., https://your-backend.railway.app).
    // If not set, it will default to localhost:8000 which will 404 on Vercel.
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;
