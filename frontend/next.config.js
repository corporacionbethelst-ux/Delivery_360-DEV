/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  outputFileTracingRoot: __dirname,
  // Optional for disk-constrained development environments; CI keeps its normal cache.
  webpack(config) {
    if (process.env.DELIVERY360_DISABLE_WEBPACK_CACHE === '1') config.cache = false;
    return config;
  },
};

module.exports = nextConfig;
