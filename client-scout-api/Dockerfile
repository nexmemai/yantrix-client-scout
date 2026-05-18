FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.11-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/scout \
    PLAYWRIGHT_BROWSERS_PATH=/home/scout/.cache/ms-playwright \
    SNAPSHOT_DIR=/app/snapshots

RUN groupadd --system scout \
    && useradd --system --gid scout --create-home --home-dir /home/scout --shell /usr/sbin/nologin scout \
    && mkdir -p /home/scout/.cache/ms-playwright /app \
    && chown -R scout:scout /home/scout /app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    libpq5 \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-xcb1 libxcb1 libxext6 \
    libxcb-dri3-0 libdbus-1-3 libatspi2.0-0 fonts-liberation \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY --chown=scout:scout . .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN python -m playwright install-deps chromium \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /app/scripts/ingest_gmaps_csv.py \
    && mkdir -p /app/snapshots \
    && chown -R scout:scout /app/snapshots \
    && rm -rf /var/lib/apt/lists/*

# Install the browser while running as the same user used at runtime. This keeps
# the executable path and permissions stable across rebuilds and container starts.
RUN gosu scout sh -c "python -m playwright install chromium && python -c \"from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage']); b.close(); p.stop(); print('Playwright Chromium launch check OK')\""

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')"

ENTRYPOINT ["docker-entrypoint.sh"]

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop", \
     "--http", "h11", \
     "--access-log", \
     "--log-level", "info"]
