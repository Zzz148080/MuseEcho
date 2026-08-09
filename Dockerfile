FROM node:22.23.0-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM golang:1.26.5-alpine3.23 AS gateway-builder
RUN apk add --no-cache ca-certificates git
RUN --mount=type=cache,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,target=/root/.cache/go-build,sharing=locked \
    set -eu; \
    go install github.com/caddyserver/xcaddy/cmd/xcaddy@v0.4.6; \
    attempt=1; \
    until xcaddy build v2.11.4 \
        --output /usr/bin/caddy \
        --replace golang.org/x/text=golang.org/x/text@v0.39.0 \
        --replace google.golang.org/grpc=google.golang.org/grpc@v1.82.1; do \
        if [ "$attempt" -ge 5 ]; then \
            exit 1; \
        fi; \
        attempt=$((attempt + 1)); \
        sleep $((attempt * 2)); \
    done

FROM python:3.12.13-slim-bookworm AS python-builder
ENV UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1
WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.11.29
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --compile-bytecode

FROM python:3.12.13-slim-bookworm AS app
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR=/tmp/numba \
    MUSEECHO_DATA_ROOT=/data \
    MUSEECHO_AUDIO_KEK_FILE=/run/secrets/audio-kek
RUN --mount=type=cache,target=/var/cache/museecho-apt,sharing=locked \
    set -eu; \
    sed -i "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    apt-get -o Acquire::Retries=5 update; \
    mkdir --parents /var/cache/museecho-apt/partial; \
    attempt=1; \
    until apt-get \
        -o Acquire::Retries=2 \
        -o Dir::Cache::Archives=/var/cache/museecho-apt \
        install --yes --no-install-recommends ca-certificates ffmpeg; do \
        if [ "$attempt" -ge 5 ]; then \
            exit 1; \
        fi; \
        attempt=$((attempt + 1)); \
        sleep $((attempt * 2)); \
    done; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 10001 museecho; \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin museecho; \
    mkdir --parents /app /data; \
    chown --recursive 10001:10001 /app /data
WORKDIR /app
COPY --from=python-builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 src/ /app/src/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read()"]
CMD ["uvicorn", "museecho.runtime:app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM caddy:2.11.4-alpine AS gateway
ENV XDG_DATA_HOME=/tmp/caddy/data \
    XDG_CONFIG_HOME=/tmp/caddy/config
RUN apk upgrade --no-cache c-ares curl libcurl \
    && setcap -r /usr/bin/caddy
COPY --from=gateway-builder /usr/bin/caddy /usr/bin/caddy
COPY --from=frontend-builder /build/frontend/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
USER 10001:10001
EXPOSE 8080 8443
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["wget", "--no-check-certificate", "--quiet", "--spider", "https://127.0.0.1:8443/api/health"]
