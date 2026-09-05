# ==============================================================================
# Backend image.
#
# Runs Gunicorn with Uvicorn workers, per spec section 22. Gunicorn depends on
# POSIX `fcntl` and therefore cannot run on Windows -- this image is how the
# production process manager is exercised from a Windows development machine.
# ==============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# Build dependencies for psycopg and cryptography wheels.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copied separately so the dependency layer is cached across source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Never run as root (spec section 27).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:8000/api/v1/health || exit 1

# Worker count is configurable per spec section 22.
CMD ["sh", "-c", "gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WORKERS:-4} \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --timeout 60 \
    --graceful-timeout 30"]
