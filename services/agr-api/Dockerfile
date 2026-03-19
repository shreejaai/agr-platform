# Multi-stage production Dockerfile for agr-api
# Build context: repo root  (docker compose sets context: .)
#
# Stage 1: install Python dependencies
FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/agr-api/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: lean runtime image
FROM python:3.12-slim

# Non-root user
RUN groupadd --gid 1001 agr && useradd --uid 1001 --gid agr --no-create-home agr

WORKDIR /app

# Installed packages from builder
COPY --from=builder /install /usr/local

# API source
COPY --chown=agr:agr services/agr-api/ .

# agr-core package (cedar_service.py imports from here)
COPY --chown=agr:agr packages/ /packages/

USER agr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
