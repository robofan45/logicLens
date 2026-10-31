# syntax=docker/dockerfile:1
# LogicLens web app: static build served by unprivileged nginx, /api proxied to the backend.
#   docker build -t logiclens-web web/
# Base images are pinned by tag; pin by digest in production and bump deliberately.

FROM node:22-alpine AS build
WORKDIR /app
ENV npm_config_fund=false npm_config_audit=false
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts postcss.config.mjs ./
COPY public ./public
COPY src ./src
# Same-origin by default (nginx proxies /api); set only if the API lives on another origin.
ARG VITE_API_BASE=
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=4s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
