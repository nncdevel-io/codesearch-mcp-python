# Verify pipeline for AI agents and CI (harness report §2.3 / §2.8).
# Run all gates with: make verify
#
# Each target is a thin wrapper over a single tool; verify chains them with
# fail-fast semantics. Make is the aggregator instead of taskipy so the
# pipeline runs without installing the project itself.

.PHONY: help verify lint format format-check types imports test test-fast coverage audit md spell sync clean

UV ?= uv

help:
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

sync: ## Install/refresh deps from uv.lock
	$(UV) sync --frozen

lint: ## Ruff lint check
	$(UV) run ruff check src tests

format: ## Apply ruff format
	$(UV) run ruff format src tests

format-check: ## Ruff format check (no write)
	$(UV) run ruff format --check src tests

types: ## Pyrefly type check
	$(UV) run pyrefly check

imports: ## import-linter layer contract check
	$(UV) run lint-imports

test: ## pytest with coverage gate
	$(UV) run coverage run -m pytest -q
	$(UV) run coverage report

test-fast: ## pytest only, no coverage
	$(UV) run pytest -q

coverage: ## Print coverage report only (no re-run)
	$(UV) run coverage report

audit: ## pip-audit dependency vulnerability scan
	# PYSEC-2025-183 (CVE-2025-45768): disputed by PyJWT maintainers — key length
	# is the application's responsibility, no upstream fix exists, and pyjwt is
	# a transitive dep via mcp (not used directly by this project).
	$(UV) run pip-audit --skip-editable --ignore-vuln PYSEC-2025-183

md: ## Markdown lint
	markdownlint-cli2 README.md CHANGELOG.md docs

spell: ## Spell check (cspell)
	cspell --no-progress --config cspell.json "README.md" "CHANGELOG.md" "docs/**/*.md"

verify: lint format-check types imports test audit md spell ## Run the full verify pipeline

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov .pyrefly_cache .cspellcache
