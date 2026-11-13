/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  transpilePackages: [
    "three",
    "@react-three/fiber",
    "@react-three/postprocessing",
    "postprocessing"
  ],

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
      {
        source: "/health/:path*",
        destination: "http://127.0.0.1:8000/health/:path*",
      },
    ];
  },

  webpack: (config) => {
    config.module.rules.push({
      test: /\.(glsl|vs|fs|vert|frag)$/,
      type: "asset/source",
    });
    return config;
  },
};

module.exports = nextConfig;
