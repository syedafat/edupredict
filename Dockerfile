# ==============================================================================
# EduPredict — Production Dockerfile
# Multi-arch compatible, unprivileged user, production Gunicorn WSGI runtime.
# ==============================================================================

FROM python:3.12-slim AS runtime

# Set runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_ENV=production \
    PORT=5000 \
    GUNICORN_WORKERS=4 \
    GUNICORN_THREADS=2 \
    GUNICORN_TIMEOUT=120

# Install required system packages (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user & group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Set working directory
WORKDIR /app

# Install exact, hash-verified Python dependencies first for caching efficiency.
COPY requirements-prod.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements-prod.lock

# Copy application source code
COPY --chown=appuser:appgroup . .

# Ensure upload and model storage directories exist and are owned by appuser
RUN mkdir -p /app/uploads /app/models && \
    chown -R appuser:appgroup /app/uploads /app/models /app

# Switch to unprivileged user
USER appuser

# Expose web service port
EXPOSE 5000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/health || exit 1

# Production WSGI launch command
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers ${GUNICORN_WORKERS:-4} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --access-logformat '%(h)s %(t)s \"%(m)s %(U)s %(H)s\" %(s)s %(b)s' --error-logfile - wsgi:app"]
