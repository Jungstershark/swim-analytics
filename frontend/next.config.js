/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
  // Increase proxy timeout for large ZIP uploads (default 30s is too short)
  experimental: {
    proxyTimeout: 120000,
  },
};

module.exports = nextConfig;
