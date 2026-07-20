# Build via: make frontend-image-build (tags via immutable IMAGE_TAG / git describe)

FROM node:22-bookworm-slim AS builder

RUN corepack enable && corepack prepare pnpm@10.28.2 --activate

WORKDIR /app

COPY frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/
COPY frontend/apps/admin/package.json frontend/apps/admin/

RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm --dir frontend install --frozen-lockfile

COPY frontend/apps/admin/ frontend/apps/admin/

RUN pnpm --dir frontend --filter admin build

FROM nginx:1.31.3-alpine

RUN apk upgrade --no-cache libcrypto3 libssl3 libxml2 \
    && rm /etc/nginx/conf.d/default.conf \
    && mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp \
    && chown -R 101:101 /tmp/nginx /usr/share/nginx/html /var/cache/nginx /var/log/nginx

COPY --from=builder /app/frontend/apps/admin/dist /usr/share/nginx/html
COPY frontend/apps/admin/nginx.conf /etc/nginx/nginx.conf

USER 101:101

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
