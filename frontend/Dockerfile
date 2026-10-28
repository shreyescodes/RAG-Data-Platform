# syntax=docker/dockerfile:1

# ---- Build static assets -------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Leave as /api to have nginx proxy (and authenticate) API calls.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- Serve with nginx ------------------------------------------------------------
FROM nginx:1.27-alpine
# The official image renders /etc/nginx/templates/*.template with envsubst.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

ENV BACKEND_URL=http://backend:8000 \
    API_KEY=""
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz >/dev/null || exit 1
