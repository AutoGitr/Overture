# syntax=docker/dockerfile:1.28@sha256:bb22d9815c728170f72750f4e5b0d672e06176142e1d602c7e66c050100b7e5b
# apt packages track the pinned base image rather than pinned versions.
# hadolint global ignore=DL3008

# Vite emits architecture-independent assets; avoid emulation for arm64 releases.
FROM --platform=$BUILDPLATFORM oven/bun:1.4.4-slim@sha256:1846adf22496bd711036aae8be147e57bdebbaea2e5264e3e0b5af1db187d9a4 AS frontend

WORKDIR /build

COPY frontend/package.json frontend/bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile && \
    mkdir -p /licenses/frontend && \
    find node_modules -type f \( -iname 'license*' -o -iname 'copying*' -o -iname 'notice*' \) \
        -exec cp --parents -t /licenses/frontend/ '{}' +

COPY frontend/ .
RUN bun run build

FROM python:3.15.1-slim@sha256:08275f764e022331c6d3e3ca55d8cce01fa4684b02111adf0445d71806fe7941 AS python-base

FROM astral/uv:0.13.5 AS uv

# The image and the native archive ship the same pinned tools.
FROM denoland/deno:bin-2.9.6@sha256:4cf0029b9aeeeed5efcbb71828737f0d7c8c8a20072df960e51a5679ef0d21ba AS deno
FROM mwader/static-ffmpeg:9.0.2@sha256:7d9bdaaf887f7e6ce6151f67325c344074b5ff1fb75316011c3376503e449a7b AS ffmpeg

FROM python-base AS backend-deps

# Precompile once in the cached dependency layer for repeated yt-dlp subprocesses.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project && \
    mkdir -p /licenses/python && \
    find .venv/lib/python3.15/site-packages -type f \
        \( -path '*dist-info/licenses/*' -o -iname 'license*' -o -iname 'copying*' -o -iname 'notice*' \) \
        -exec cp --parents -t /licenses/python/ '{}' +

FROM backend-deps AS application
COPY src/ ./src
COPY .github/README.md ./.github/README.md
COPY LICENSE ./
COPY --from=frontend /src/overture/frontend ./src/overture/frontend
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable && \
    uv build --wheel --out-dir /dist

# The native archive: python-build-standalone with the same locked packages and tools.
FROM application AS native-build
ENV UV_PYTHON_DOWNLOADS=manual
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends binutils && \
    rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=deno /deno /build/tools/
COPY --from=ffmpeg /ffmpeg /ffprobe /build/tools/
COPY --from=frontend /licenses/frontend/ /build/licenses/dependencies/frontend/
COPY LICENSE licenses/ /build/licenses/
COPY packaging/linux/build.py packaging/linux/install.sh packaging/linux/uninstall.sh \
    packaging/linux/overture packaging/linux/python packaging/linux/overture.service /build/
RUN --mount=type=cache,target=/root/.cache/uv \
    .venv/bin/python /build/build.py --project . --output /out

FROM scratch AS native-artifact
COPY --from=native-build /out/ /

# The default build target, so it stays the last stage.
FROM python-base AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OVERTURE_CONFIG_DIR=/config \
    OVERTURE_HOST=0.0.0.0 \
    DENO_DIR=/tmp/deno \
    XDG_CACHE_HOME=/tmp/cache \
    TZ=UTC \
    PATH="/app/.venv/bin:$PATH"

# Keep apt downloads across builds, without putting them in image layers.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates tzdata && \
    groupadd --gid 1000 overture && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin overture && \
    install -d -o overture -g overture -m 0750 /config && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* /etc/apt /usr/bin/apt* /usr/bin/dpkg* /usr/local/lib/python*/site-packages/*

COPY --from=deno /deno /usr/local/bin/deno
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

WORKDIR /app

COPY --from=backend-deps /app/.venv ./.venv
# Overture gets its own small layer, so an update that keeps the dependencies
# downloads only that.
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=from=application,source=/dist,target=/dist \
    uv pip install --python .venv/bin/python --no-deps --no-cache \
        --compile-bytecode --link-mode copy /dist/overture-*.whl
COPY --from=backend-deps /licenses/python/ /usr/share/licenses/overture/dependencies/python/
COPY --from=frontend /licenses/frontend/ /usr/share/licenses/overture/dependencies/frontend/
COPY LICENSE /usr/share/licenses/overture/
COPY licenses/ /usr/share/licenses/overture/

# Release metadata must not invalidate the cached layers above.
ARG APP_VERSION=development
ARG BUILD_DATE=unknown
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="Overture" \
      org.opencontainers.image.description="Artwork and theme manager for Plex, Jellyfin and Emby" \
      org.opencontainers.image.source="https://github.com/AutoGitr/Overture" \
      org.opencontainers.image.url="https://github.com/AutoGitr/Overture" \
      org.opencontainers.image.documentation="https://github.com/AutoGitr/Overture#readme" \
      org.opencontainers.image.created="$BUILD_DATE" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

USER 1000:1000

EXPOSE 5885

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5885/api/ready', timeout=5)"]

ENTRYPOINT ["overture"]
CMD ["serve"]
