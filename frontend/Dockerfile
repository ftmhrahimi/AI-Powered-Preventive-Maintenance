# ── Stage 1: production build (minify markup + inline CSS/JS) ──
FROM node:20-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY build.mjs index.html ./
RUN node build.mjs

# ── Stage 2: runtime ──
FROM nginx:alpine

COPY nginx.conf      /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist/index.html /usr/share/nginx/html/index.html
COPY task_rules.json /usr/share/nginx/html/task_rules.json
COPY js/             /usr/share/nginx/html/js/
COPY config.js       /etc/nginx/templates/config.js.template

# The official nginx entrypoint renders /etc/nginx/templates/*.template with
# envsubst at startup; this makes it write config.js into the web root.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:80/ || exit 1
