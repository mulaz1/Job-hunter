# ============================================================
# Job Hunter — Dockerfile
# Python 3.12 slim with Playwright Chromium
# ============================================================

FROM python:3.12-slim

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y \
    # Core utilities
    curl \
    wget \
    ca-certificates \
    # Playwright browser dependencies
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libwayland-client0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only to minimize image size)
RUN playwright install chromium

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# Create persistent data directory
RUN mkdir -p /app/data

# Run as non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /ms-playwright
USER appuser

# Health check: verify the process is running
HEALTHCHECK --interval=5m --timeout=30s --start-period=60s --retries=3 \
    CMD python -c "import os; exit(0 if os.path.exists('/app/data/jobs.db') else 1)"

# Entry point
CMD ["python", "-m", "src.main"]
