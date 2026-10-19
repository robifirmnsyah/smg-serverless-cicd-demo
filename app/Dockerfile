# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

# Prevent Python from writing .pyc files and enable unbuffered logging for Cloud Logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

# Allow setting version at build time or overriding at Cloud Run deploy time
ARG APP_VERSION=v1
ENV APP_VERSION=${APP_VERSION} \
    MIN_INSTANCES=0 \
    MAX_INSTANCES=10

WORKDIR /app

# Create a non-root user and group for container security best practices
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --shell /sbin/nologin --no-create-home appuser

# Install Python dependencies first to leverage Docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and templates with proper ownership
COPY --chown=appuser:appgroup . ./

# Switch to non-root user
USER appuser

# Cloud Run injects the PORT environment variable (default 8080)
EXPOSE 8080

# Use exec form via shell to expand $PORT and forward SIGTERM cleanly for graceful scale-down
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
