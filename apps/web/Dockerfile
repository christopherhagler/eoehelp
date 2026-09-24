# Built by buildah in CI and by podman locally. No BuildKit-only syntax is used.
#
#   deps ─ builder ─ runtime
#
# `deps` owns node_modules and is what the dev server and every web tool run in.
# Configuration files are copied rather than mounted, so a dependency or config
# change is a content change that rebuilds the image — which is the point: the
# previous arrangement used a named volume for node_modules, and a named volume
# is a snapshot that never updates. That is what left the dev server running
# against dependencies from whenever the volume was first created.

# ---- deps -------------------------------------------------------------------
FROM node:24-bookworm-slim AS deps

WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci

# Installed globally at the pinned version rather than added to package.json:
# openapi-typescript 7 declares a peer dependency on typescript ^5 and this
# project is on 6, so it would be an unsatisfiable constraint in the lock file.
# In the image it also stops `just api-types` reaching the network every run.
RUN npm install -g openapi-typescript@7.13.0

# Config the toolchain reads. Copied, not mounted: these change rarely, and a
# change to one should rebuild rather than silently apply to a stale image.
COPY angular.json tsconfig*.json .postcssrc.json .prettierrc .prettierignore ./

# ---- builder ----------------------------------------------------------------
FROM deps AS builder

COPY . .
RUN npm run build -- --configuration production

# ---- runtime ----------------------------------------------------------------
# Serves the compiled SPA. The same image is promoted by digest to the deployed
# environment, so what runs there is what was built and tested here.
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
