FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (installed before COPY . . for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browser install — path must be set BEFORE install so browsers land in a
# location that the non-root user (re_os, uid 1001) can access at runtime.
# Setting it here (before USER re_os) makes it available to the RUN command below.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium

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
    && useradd --uid 1001 --gid re_os --create-home re_os \
    && chown -R re_os:re_os /app /ms-playwright /home/re_os

USER re_os

ENV PYTHONUNBUFFERED=1

CMD ["python", "crews/market_intel_crew.py"]
