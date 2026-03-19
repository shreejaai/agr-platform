# Multi-stage production Dockerfile for agr-api
# Stage 1: install dependencies
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: lean runtime image
FROM python:3.12-slim

# Run as non-root for security
RUN groupadd --gid 1001 agr && useradd --uid 1001 --gid agr --no-create-home agr

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source (packages dir lives at ../../packages relative to service context;
# mount it at runtime or bake it in via docker-compose build context if needed)
COPY --chown=agr:agr . .

USER agr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
