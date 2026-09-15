# Built by buildah in CI and by podman locally. No BuildKit-only syntax is used.

# ---- builder ----------------------------------------------------------------
FROM node:24-bookworm-slim AS builder

WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build -- --configuration production

# ---- runtime ----------------------------------------------------------------
# Serves the compiled SPA. In AWS the same build artifact is uploaded to S3 and
# fronted by CloudFront; this image exists so local and CI runs are identical.
FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/* \
 && rm /etc/nginx/conf.d/default.conf

COPY nginx/app.conf /etc/nginx/conf.d/app.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=builder /build/dist/web/browser /usr/share/nginx/html

# nginx:alpine ships an unprivileged `nginx` user; bind high port so no root is needed.
RUN touch /var/run/nginx.pid \
 && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost:8080/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
