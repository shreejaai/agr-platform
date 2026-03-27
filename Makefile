# AGR Platform — developer convenience targets
# Run `make help` for a quick reference.

.PHONY: help lint typecheck test test-unit test-integration test-postgres \
        test-sdk-py test-sdk-ts test-cedar test-dashboard \
        dev dev-infra dev-dashboard build-dashboard \
        migrate review-package clean

# ── Formatting ────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "AGR Platform — available targets"
	@echo ""
	@echo "  lint               ruff check + format check (whole repo)"
	@echo "  typecheck          mypy for backend + tsc for TS SDK"
	@echo "  test               all fast tests (unit + integration, no PG)"
	@echo "  test-unit          backend unit tests only"
	@echo "  test-integration   backend integration tests only"
	@echo "  test-postgres      backend tests against real PostgreSQL"
	@echo "  test-sdk-py        Python SDK lint + type-check"
	@echo "  test-sdk-ts        TypeScript SDK type-check + test + build"
	@echo "  test-cedar         Cedar CLI policy engine tests"
	@echo "  test-dashboard     Angular lint + test"
	@echo "  dev                docker compose up (API + dashboard + infra)"
	@echo "  dev-infra          docker compose up postgres + redis only"
	@echo "  dev-dashboard      ng serve with proxy to localhost:8000"
	@echo "  build-dashboard    production Angular build"
	@echo "  migrate            run all migrations (requires PG vars)"
	@echo "  review-package     create a clean review archive (no secrets)"
	@echo "  clean              remove build artifacts"
	@echo ""

# ── Quality gates (matches CI) ────────────────────────────────────────────────

lint:
	ruff check .
	ruff format --check .

typecheck:
	cd services/agr-api && python -m mypy app/
	cd packages/agr-sdk-ts && npm run typecheck

test: test-unit test-integration

test-unit:
	cd services/agr-api && python -m pytest tests/unit -v

test-integration:
	cd services/agr-api && python -m pytest tests/integration -v

test-postgres:
	cd services/agr-api && python -m pytest tests/postgres/ -v --tb=short

test-sdk-py:
	ruff check packages/agr-sdk-python/
	python -m mypy packages/agr-sdk-python/agr/ --ignore-missing-imports

test-sdk-ts:
	cd packages/agr-sdk-ts && npm run typecheck && npm test && npm run build

test-cedar:
	cd packages/agr-core && python -m pytest tests/test_cedar_cli.py -v

test-dashboard:
	cd apps/agr-dashboard && npm run lint && \
	  npm test -- --watch=false --browsers=ChromeHeadlessNoSandbox

# ── Development ───────────────────────────────────────────────────────────────

dev:
	docker compose up --build

dev-infra:
	docker compose up -d postgres redis

dev-dashboard:
	cd apps/agr-dashboard && npm start

build-dashboard:
	cd apps/agr-dashboard && npm run build -- --configuration production

# ── Migrations ────────────────────────────────────────────────────────────────

migrate:
	@echo "Running migrations against $$POSTGRES_HOST..."
	sh infra/migrate.sh

# ── Review packaging ─────────────────────────────────────────────────────────
#
# Creates a clean tar.gz suitable for external code review or handoff.
# Excludes: git history, secrets, node_modules, venv, build artifacts, caches.
#
# Output: /tmp/agr-platform-review-<YYYYMMDD>.tar.gz
#
# Usage:
#   make review-package
#   ls -lh /tmp/agr-platform-review-*.tar.gz
#
REVIEW_DATE := $(shell date +%Y%m%d)
REVIEW_ARCHIVE := /tmp/agr-platform-review-$(REVIEW_DATE).tar.gz

review-package:
	@echo "Building review archive → $(REVIEW_ARCHIVE)"
	@tar \
	  --exclude='.git' \
	  --exclude='.env' \
	  --exclude='.env.*' \
	  --exclude='*.pem' \
	  --exclude='*.key' \
	  --exclude='*.p12' \
	  --exclude='*.pfx' \
	  --exclude='*.cer' \
	  --exclude='*.crt' \
	  --exclude='node_modules' \
	  --exclude='**/node_modules' \
	  --exclude='.venv' \
	  --exclude='**/.venv' \
	  --exclude='venv' \
	  --exclude='**/venv' \
	  --exclude='dist' \
	  --exclude='**/dist' \
	  --exclude='build' \
	  --exclude='**/build' \
	  --exclude='.angular' \
	  --exclude='**/.angular' \
	  --exclude='__pycache__' \
	  --exclude='**/__pycache__' \
	  --exclude='*.pyc' \
	  --exclude='*.pyo' \
	  --exclude='*.so' \
	  --exclude='.pytest_cache' \
	  --exclude='**/.pytest_cache' \
	  --exclude='.mypy_cache' \
	  --exclude='**/.mypy_cache' \
	  --exclude='.ruff_cache' \
	  --exclude='**/.ruff_cache' \
	  --exclude='htmlcov' \
	  --exclude='.coverage' \
	  --exclude='*.egg-info' \
	  --exclude='.DS_Store' \
	  --exclude='Thumbs.db' \
	  --exclude='.claude' \
	  --exclude='uv.lock' \
	  --exclude='reports/*.pdf' \
	  -czf $(REVIEW_ARCHIVE) \
	  -C "$(dir $(abspath $(lastword $(MAKEFILE_LIST))))" \
	  .
	@echo ""
	@echo "Archive created: $(REVIEW_ARCHIVE)"
	@echo "Size:            $$(du -sh $(REVIEW_ARCHIVE) | cut -f1)"
	@echo ""
	@echo "Verify no secrets leaked:"
	@echo "  tar -tzf $(REVIEW_ARCHIVE) | grep -E '\\.env|\\.pem|\\.key'"
	@echo ""

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -not -path '*/node_modules/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -not -path '*/node_modules/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -not -path '*/node_modules/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -not -path '*/node_modules/*' -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -not -path '*/node_modules/*' -delete 2>/dev/null || true
	rm -rf apps/agr-dashboard/dist apps/agr-dashboard/.angular 2>/dev/null || true
	rm -rf packages/agr-sdk-ts/dist 2>/dev/null || true
	@echo "Clean done."
