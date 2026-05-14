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

# Non-root user for security
RUN groupadd -r scout && useradd -r -g scout scout

WORKDIR /app

# System deps needed at runtime (asyncpg needs libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    # Playwright Chromium runtime deps
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=scout:scout . .

# Install Playwright browser (Chromium only — smallest footprint)
# Phase 3: uncomment when Playwright is fully wired
# RUN playwright install chromium --with-deps

# Switch to non-root
USER scout

# Expose API port
EXPOSE 8000

# Health check — used by Docker Compose and orchestrators
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
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
