# ── Build Stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Production Stage ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS production

# Non-root user with a real, writable home directory.
# -m creates /home/scout; Playwright needs ~/.cache/ms-playwright/ to exist.
RUN groupadd -r scout && useradd -r -g scout -m -d /home/scout scout

WORKDIR /app

# System deps needed at runtime (asyncpg needs libpq; Playwright needs the rest)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    # Playwright Chromium runtime deps
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 \
    # Extra libs sometimes needed by Chromium on slim images
    libpango-1.0-0 libcairo2 libx11-xcb1 libxcb1 libxext6 \
    libxcb-dri3-0 libdbus-1-3 libatspi2.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=scout:scout . .

# ── Install Playwright Chromium at build time ─────────────────────────────────
# Deterministic path — same at build and runtime. No manual install needed.
ENV PLAYWRIGHT_BROWSERS_PATH=/home/scout/.cache/ms-playwright
RUN playwright install chromium \
    && chown -R scout:scout /home/scout

# Switch to non-root
USER scout

# Expose API port
EXPOSE 8000

# Health check — used by Docker Compose and orchestrators
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Production server — single worker per container; scale horizontally
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop", \
     "--http", "h11", \
     "--access-log", \
     "--log-level", "info"]
