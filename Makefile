# Developer shortcuts. Everything here is also what CI runs (.github/workflows/ci.yml).
PY := .venv/bin/python
RUFF := .venv/bin/ruff
PYRIGHT := .venv/bin/pyright

.PHONY: help setup lint format typecheck test test-all web-install web-check web-build check clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install Python (CPU wheels, with benchmark tools) and web dependencies
	uv sync --extra cpu --group bench
	cd web && npm ci

lint: ## ruff lint + format check
	$(RUFF) check .
	$(RUFF) format --check .

format: ## Auto-format and auto-fix
	$(RUFF) check --fix .
	$(RUFF) format .

typecheck: ## pyright (strict)
	$(PYRIGHT)

test: ## Unit tests that need no model weights
	$(PY) -m pytest -m "not models and not docker and not gpu"

test-all: ## Everything, including tests that need downloaded models
	$(PY) -m pytest --cov --cov-report=term-missing

web-install:
	cd web && npm ci

web-check: ## Frontend typecheck, lint and unit tests
	cd web && npm run typecheck && npm run lint && npm test

web-build: ## Build the web app into web/dist (served by `kf serve`)
	cd web && npm run build

check: lint typecheck test web-check ## Everything CI checks, minus model-dependent tests

clean:
	rm -rf .pytest_cache .pytest_tmp .ruff_cache .coverage htmlcov web/dist
