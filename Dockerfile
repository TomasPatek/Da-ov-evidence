# syntax=docker/dockerfile:1

FROM python:3.15-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY app ./app
# Source permissions vary (e.g. 0700 dirs from an unzipped archive); the app runs as uid 1000.
RUN chmod -R u=rwX,go=rX /app \
    && uv sync --frozen --no-dev

FROM python:3.15-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core libzbar0 \
        tesseract-ocr tesseract-ocr-ces restic rclone ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data /config \
    && chown app:app /data /config
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    CONFIG_DIR=/config \
    TZ=Europe/Prague \
    RCLONE_CONFIG=/config/rclone/rclone.conf \
    RESTIC_CACHE_DIR=/tmp/restic-cache \
    XDG_CACHE_HOME=/tmp/.cache
USER app
VOLUME ["/data", "/config"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/zdravi').status != 200)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
