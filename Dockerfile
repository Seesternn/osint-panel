# syntax=docker/dockerfile:1.7
#
# OSINT Panel — container image
#
#   docker compose up -d --build                       → http://127.0.0.1:5050
#   docker build --build-arg WITH_GEOCLIP=1 -t osint-panel .   (adds the ~1 GB photo-geolocation model)
#
# Stage 1 installs every tool (needs compilers and git); stage 2 only carries the result plus runtime
# packages, runs as an unprivileged user and keeps all user data in the /data volume.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

############################ builder ############################
FROM ${PYTHON_IMAGE} AS builder

ARG WITH_GEOCLIP=0
ARG WITH_GO_TOOLS=1
ARG SUBFINDER_VERSION=2.6.6
ARG HTTPX_VERSION=1.6.9
ARG PHONEINFOGA_VERSION=2.11.0
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/tmp/uv-cache

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git curl ca-certificates unzip libxml2-dev libxslt1-dev libffi-dev \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

# Python tools (each in its own virtual environment, exactly like a local install)
RUN --mount=type=cache,target=/tmp/uv-cache \
    export SKIP_SYSTEM_CHECK=1 \
 && if [ "$WITH_GEOCLIP" = "1" ]; then ./setup.sh; else ./setup.sh --no-geoclip; fi \
 && rm -f tools/searxng/settings.yml \
 && find /app -name "__pycache__" -type d -prune -exec rm -rf {} + \
 && rm -rf /app/sherlock/.git /app/tools/*/.git /app/tools/searxng/src/.git

# Go tools: subfinder, httpx, PhoneInfoga (optional; a failed download only disables that tool)
RUN mkdir -p /opt/bin && cd /tmp && if [ "$WITH_GO_TOOLS" = "1" ]; then \
      ARCH="${TARGETARCH:-amd64}"; case "$ARCH" in arm64) PI=arm64 ;; *) PI=x86_64 ;; esac; \
      ( curl -fsSLo s.zip "https://github.com/projectdiscovery/subfinder/releases/download/v${SUBFINDER_VERSION}/subfinder_${SUBFINDER_VERSION}_linux_${ARCH}.zip" \
        && unzip -oq s.zip subfinder -d /opt/bin ) || echo "subfinder skipped"; \
      ( curl -fsSLo h.zip "https://github.com/projectdiscovery/httpx/releases/download/v${HTTPX_VERSION}/httpx_${HTTPX_VERSION}_linux_${ARCH}.zip" \
        && unzip -oq h.zip httpx -d /opt/bin ) || echo "httpx skipped"; \
      ( curl -fsSL "https://github.com/sundowndev/phoneinfoga/releases/download/v${PHONEINFOGA_VERSION}/phoneinfoga_Linux_${PI}.tar.gz" \
        | tar -xz -C /opt/bin phoneinfoga ) || echo "phoneinfoga skipped"; \
      rm -f /tmp/*.zip; \
    fi; chmod -R a+rx /opt/bin

############################ runtime ############################
FROM ${PYTHON_IMAGE}

LABEL org.opencontainers.image.title="OSINT Panel" \
      org.opencontainers.image.description="One search box for ~50 open-source intelligence tools" \
      org.opencontainers.image.authors="Seesternn" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates tini libimage-exiftool-perl ffmpeg chromium fonts-noto-core fonts-noto-cjk \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-tur libxml2 libxslt1.1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin osint \
 && mkdir -p /data && chown osint:osint /data

COPY --from=builder /opt/uv-python /opt/uv-python
COPY --from=builder /opt/bin /opt/bin
COPY --from=builder --chown=osint:osint /app /app
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/osint-entrypoint

ENV PATH="/opt/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    OSINT_DATA_DIR=/data \
    HOME=/data/home \
    HF_HOME=/data/hf-cache \
    PANEL_HOST=0.0.0.0 \
    PORT=5050 \
    CHROME_PATH=/usr/bin/chromium \
    CHROME_NO_SANDBOX=1 \
    TESSERACT_LANGS=eng+tur

WORKDIR /app
USER osint
EXPOSE 5050
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/healthz', timeout=4)"]

ENTRYPOINT ["tini", "--", "osint-entrypoint"]
CMD ["/app/.venv/bin/python", "/app/panel/app.py"]
