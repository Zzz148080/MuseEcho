ARG SOURCE_DATE_EPOCH=1785888000

FROM node:22.23.0-bookworm-slim@sha256:d9f850096136edbc402debdd8729579a288aac64574ada0ff4db26b6ae58b0b2 AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM golang:1.26.6-alpine3.23@sha256:5978cc992ad5ef96a7469713c8af849c1433824761ce3be2c56381403cd8d9a3 AS gateway-builder
ENV GOTOOLCHAIN=local \
    GOPROXY=https://proxy.golang.org
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

FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS python-builder
ARG SOURCE_DATE_EPOCH
ENV UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1 \
    SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
    PYTHONHASHSEED=0
WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.11.29
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --compile-bytecode \
    && find .venv -type f -name '*.pyc' -delete \
    && find .venv -type d -name __pycache__ -empty -delete
COPY src/ /app/src/
RUN uv sync --frozen --no-dev --no-editable --compile-bytecode \
    && find .venv -type f -name '*.pyc' -delete \
    && find .venv -type d -name __pycache__ -empty -delete

FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS app
ARG DEBIAN_SNAPSHOT=20260805T000000Z
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR=/tmp/numba \
    MUSEECHO_DATA_ROOT=/data \
    MUSEECHO_AUDIO_KEK_FILE=/run/secrets/audio-kek
RUN --mount=type=cache,target=/var/cache/museecho-apt,sharing=locked \
    set -eu; \
    printf '%s\n' \
        'Types: deb' \
        "URIs: https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" \
        'Suites: bookworm bookworm-updates' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        'Check-Valid-Until: no' \
        '' \
        'Types: deb' \
        "URIs: https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}" \
        'Suites: bookworm-security' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        'Check-Valid-Until: no' \
        > /etc/apt/sources.list.d/debian.sources; \
    apt-get -o Acquire::Retries=5 -o Acquire::Check-Valid-Until=false update; \
    mkdir --parents /var/cache/museecho-apt/partial; \
    attempt=1; \
    until apt-get \
        -o Acquire::Retries=2 \
        -o Dir::Cache::Archives=/var/cache/museecho-apt \
        install --yes --no-install-recommends \
            ca-certificates=20230311+deb12u1 \
            ffmpeg=7:5.1.9-0+deb12u1; do \
        if [ "$attempt" -ge 5 ]; then \
            exit 1; \
        fi; \
        attempt=$((attempt + 1)); \
        sleep $((attempt * 2)); \
    done; \
    rm -rf \
        /var/cache/fontconfig/* \
        /var/cache/ldconfig/aux-cache \
        /var/lib/apt/lists/* \
        /var/log/alternatives.log \
        /var/log/apt/* \
        /var/log/dpkg.log; \
    groupadd --gid 10001 museecho; \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin museecho; \
    mkdir --parents /app /data; \
    chown --recursive 10001:10001 /app /data
WORKDIR /app
COPY --from=python-builder --chown=10001:10001 /app/.venv /app/.venv
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read()"]
CMD ["uvicorn", "museecho.runtime:app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM caddy:2.11.4-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648 AS gateway
ENV XDG_DATA_HOME=/tmp/caddy/data \
    XDG_CONFIG_HOME=/tmp/caddy/config
RUN set -eu; \
    wget -q https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/c-ares-1.34.8-r0.apk -O /tmp/c-ares.apk; \
    wget -q https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/curl-8.20.0-r0.apk -O /tmp/curl.apk; \
    wget -q https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/libcurl-8.20.0-r0.apk -O /tmp/libcurl.apk; \
    echo '7a570d080d05e60b1256ea73586924bf9a25f468c57aae10d1cdfe7fcc3f93a2  /tmp/c-ares.apk' | sha256sum -c -; \
    echo 'dc9f2b821e2ce3c578dc6e68dd79ff802d2eb05a390fb15164ad6288c815099c  /tmp/curl.apk' | sha256sum -c -; \
    echo 'a162907a766bf7828ebc894b445bf53821db406d5ed50dc987bb8a1933658338  /tmp/libcurl.apk' | sha256sum -c -; \
    apk add --no-network /tmp/c-ares.apk /tmp/curl.apk /tmp/libcurl.apk; \
    rm /tmp/c-ares.apk /tmp/curl.apk /tmp/libcurl.apk /var/log/apk.log; \
    setcap -r /usr/bin/caddy
COPY --from=gateway-builder /usr/bin/caddy /usr/bin/caddy
COPY --from=frontend-builder /build/frontend/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
USER 10001:10001
EXPOSE 8080 8443
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["wget", "--no-check-certificate", "--quiet", "--spider", "https://127.0.0.1:8443/api/health"]
