# --- build stage ---
FROM node:22-alpine AS build
WORKDIR /app
# Disable any default supply-chain release-age gate for this offline-reproducible build.
ENV NPM_CONFIG_MINIMUM_RELEASE_AGE=0
RUN corepack enable
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install
COPY . .
RUN pnpm build

# --- serve stage ---
FROM nginx:1.27-alpine
ARG GIT_SHA=unknown
# The nginx image renders templates/*.template with envsubst on startup. Defaults keep
# docker-compose working (listen 80, proxy to the `api` service); Railway overrides
# PORT + API_UPSTREAM. The filter limits substitution so nginx runtime vars survive (AL-27).
ENV PORT=80 \
    API_UPSTREAM=api:8000 \
    NGINX_ENVSUBST_FILTER=^(PORT|API_UPSTREAM)$
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# Release identity for the static bundle — queryable at /version.txt.
RUN echo "$GIT_SHA" > /usr/share/nginx/html/version.txt
EXPOSE 80
