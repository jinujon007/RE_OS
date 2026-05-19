FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (installed before COPY . . for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright — installs its own Chromium; runs as root here so browsers install to /root
RUN playwright install chromium --with-deps

# App code
COPY . .

# Create all required runtime directories
RUN mkdir -p \
    /app/outputs/yelahanka/checkpoints \
    /app/outputs/devanahalli/checkpoints \
    /app/outputs/hebbal/checkpoints \
    /app/logs

# Non-root user — run the application as re_os, not root
RUN groupadd --gid 1001 re_os \
    && useradd --uid 1001 --gid re_os --no-create-home re_os \
    && chown -R re_os:re_os /app

USER re_os

ENV PYTHONUNBUFFERED=1
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
# Tell Playwright where browsers are (installed to root home during build)
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

CMD ["python", "crews/market_intel_crew.py"]
