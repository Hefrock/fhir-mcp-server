# Developer task shortcuts. Run `make help` to list targets.
# These assume an activated environment (venv or `nix develop`).

.PHONY: help install test lint format check run clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install the package with dev dependencies (editable)
	pip install -e ".[dev]"

test: ## Run the test suite
	pytest -q

lint: ## Check style and imports (no changes)
	ruff check .

format: ## Auto-fix style and import order
	ruff check --fix .

check: lint test ## Lint then test — the gate CI enforces

run: ## Run the MCP server (stdio) against $FHIR_BASE_URL
	fhir-mcp-server

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache **/__pycache__ build dist *.egg-info
