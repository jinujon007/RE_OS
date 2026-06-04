# ============================================================
# RE_OS — Multi-stage Docker build (T-751)
# Builder stage: installs system deps + Python packages
# Runtime stage: only runtime deps + compiled code
# Target: ~600MB image (from ~2GB)
# ============================================================

# ── Builder stage ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System build deps
RUN apt-get update && apt-get install -y \
    gcc libpq-dev curl \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 gdal-bin libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages to a local venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Runtime system libs only (no build tools)
# gdal-bin: runtime GDAL shared libs required by geopandas/osmnx/pyproj at import time
RUN apt-get update && apt-get install -y \
    libpq-dev curl libglib2.0-0 libnss3 libnspr4 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 postgresql-client \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Playwright browser install
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium

# App code
COPY . .

# Runtime directories
RUN mkdir -p /app/outputs/yelahanka/checkpoints \
    /app/outputs/devanahalli/checkpoints \
    /app/outputs/hebbal/checkpoints \
    /app/outputs/rajankunte/checkpoints \
    /app/logs

# Non-root user
RUN groupadd --gid 1001 re_os \
    && useradd --uid 1001 --gid re_os --create-home re_os \
    && chown -R re_os:re_os /app /ms-playwright /home/re_os

USER re_os

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "crews/market_intel_crew.py"]
