# syntax=docker/dockerfile:1.4
# Backend Dockerfile - Django REST Framework Application
# Optimized for faster rebuilds with BuildKit cache mounts

# Stage 1: Base Python image with system dependencies
FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies (rarely changes - good cache)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Dependencies (only rebuilds when requirements.txt changes)
FROM base AS dependencies

# Copy ONLY requirements file first for better caching
COPY requirements.txt .

# Install Python dependencies with pip cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install gunicorn

# Stage 3: Production
FROM base AS production

# Copy installed packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Create a non-root user for security
RUN addgroup --gid 1001 --system appgroup \
    && adduser --uid 1001 --system --gid 1001 --home /app appuser

# Set HOME environment variable
ENV HOME=/app

# Create directories and set permissions BEFORE copying code
RUN mkdir -p /app/media /app/staticfiles

# Copy application code LAST (this layer changes most often)
COPY . .

# Set permissions
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/')" || exit 1

# Default command - collect static files and run gunicorn.
# AP10b/S5 note: the assistant shares this 3x2 pool with checkout. It is kept
# safe by BOUNDS, not isolation — 20 s LLM timeout + 1 retry, one in-flight
# chat turn per account, 10/min + 100/day throttles, ~12k history budget. A
# dedicated chat worker pool (separate service + upstream) is future work; see
# DEPLOYMENT.md "Assistant worker isolation".
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn spices_backend.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 2"]
