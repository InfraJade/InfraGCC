# syntax=docker/dockerfile:1
# Jade GCC web app: static Vite build served by nginx, same-origin proxy for /api (incl. the live WebSocket).
# One image works in every environment: /config.js is generated at container start from the environment.

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

# Runtime configuration (read by docker/05-gcc-config.envsh at start-up).
#   OIDC_AUTHORITY  issuer the browser signs in against
#   OIDC_CLIENT_ID  public OIDC client (PKCE)
#   SUPERSET_URL    public Superset origin (embedded dashboards, CSP frame-src)
#   API_BASE        app API base URL for the browser; empty = same origin through this nginx (recommended)
#   API_UPSTREAM    where nginx proxies /api/ (container network)
ENV OIDC_AUTHORITY=http://localhost:8080/realms/gcc \
    OIDC_CLIENT_ID=gcc-web \
    SUPERSET_URL=http://localhost:8090 \
    API_BASE= \
    API_UPSTREAM=http://app-api:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_FILTER=^GCC_|^NGINX_LOCAL_RESOLVERS$

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --chmod=0755 docker/05-gcc-config.envsh /docker-entrypoint.d/05-gcc-config.envsh
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD wget -qO- http://127.0.0.1/healthz >/dev/null || exit 1
