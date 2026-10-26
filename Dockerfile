FROM python:3.12-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="Papple Music" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.source="https://github.com/lewisysh/papple-music" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY gamdl_web ./gamdl_web
RUN uv sync --frozen --no-dev

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    GAMDL_WEB_HOST=0.0.0.0 \
    GAMDL_WEB_DATA_DIR=/data \
    GAMDL_WEB_OUTPUT_PATH=/downloads
VOLUME ["/data", "/downloads"]
EXPOSE 8765
CMD ["python", "-m", "gamdl_web"]
