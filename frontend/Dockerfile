# syntax=docker/dockerfile:1

# ---- Build static assets -------------------------------------------------------
FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Leave as /api to have nginx proxy (and authenticate) API calls.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- Serve with nginx (non-root) ------------------------------------------------
# nginx-unprivileged runs as uid 101 and listens on 8080. Like the official
# image, it renders /etc/nginx/templates/*.template with envsubst at start.
FROM nginxinc/nginx-unprivileged:1.31-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

ENV BACKEND_URL=http://backend:8000 \
    API_KEY="" \
    PROXY_READ_TIMEOUT=300s
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
