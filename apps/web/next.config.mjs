/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output is only needed to build the container image (see
  // infra/docker/web.Dockerfile, which sets NEXT_OUTPUT_STANDALONE=1). It is off
  // by default so a local `next build` doesn't attempt the symlink-based trace
  // copy, which requires privileges Windows dev machines don't grant.
  output: process.env.NEXT_OUTPUT_STANDALONE ? "standalone" : undefined,
  // The design system ships as TypeScript source (no build step); Next transpiles
  // it as part of the app.
  transpilePackages: ["@crucible/ui"],
};

export default nextConfig;
