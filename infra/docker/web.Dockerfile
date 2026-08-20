# Next.js web dashboard image (local/full profile; production hosting decided in P9/P10).
FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/ui/package.json ./packages/ui/package.json
RUN pnpm install --frozen-lockfile --filter web...

FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app
COPY --from=deps /app ./
COPY apps/web ./apps/web
COPY packages/ui ./packages/ui
# Standalone output produces the self-contained server the runtime stage runs.
ENV NEXT_OUTPUT_STANDALONE=1
RUN pnpm --filter web build

FROM node:22-alpine AS runtime
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/apps/web/.next/standalone ./
COPY --from=build /app/apps/web/.next/static ./apps/web/.next/static
USER app
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
