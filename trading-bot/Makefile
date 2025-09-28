# Makefile for trading-bot (uv-managed Python project)
# Usage examples:
#   make install       # create venv and install project + dev deps
#   make test          # run pytest
#   make fmt lint      # format + lint with Ruff
#   make precommit     # run all git hooks locally
#   make run           # run the trading bot
#   make help          # list targets

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV := uv
PY := python

.PHONY: help venv install hooks precommit fmt lint type test smoke run clean version

help: ## Show this help with grouped commands
	@echo "Available commands:"
	@echo ""
	@echo "=� Installation & Setup:"
	@grep -E '^[a-zA-Z_\-]+:.*##.*install' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo ">� Testing & Quality:"
	@grep -E '^[a-zA-Z_\-]+:.*##.*\[(test|lint|format|type|quality|check)\]' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "=� Trading Bot Execution:"
	@grep -E '^[a-zA-Z_\-]+:.*##.*\[(run|bot|trading)\]' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "=�  Other Utilities:"
	@grep -E '^[a-zA-Z_\-]+:.*##[^[]*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# =� Installation & Setup
venv: ## Create virtual environment [install]
	@$(UV) venv

install: ## Install project in editable mode with dependencies [install]
	@$(UV) pip install -e . --group dev

hooks: ## Install git pre-commit hooks [install]
	@$(UV) pip install pre-commit
	@$(UV) run pre-commit install

# >� Testing & Quality
precommit: ## Run all pre-commit hooks (format, lint, type check) [quality]
	@$(UV) run pre-commit run -a --show-diff-on-failure

fmt: ## Format code with Ruff formatter [format]
	@$(UV) run ruff format .

lint: ## Lint with Ruff (auto-fix + fail on remaining issues) [lint]
	@$(UV) run ruff check --fix --exit-non-zero-on-fix .

type: ## Static type-check with mypy [type]
	@$(UV) run mypy --config-file=pyproject.toml bot/ || true

test: install ## Run full test suite with pytest [test]
	@$(UV) run pytest -q

# =� Trading Bot Execution
run: install ## Run the trading bot [bot]
	@$(UV) run $(PY) -m bot.main

dev: install ## Run the trading bot in development mode [run]
	@$(UV) run $(PY) -m bot.main --dev

# =�  Other Utilities
clean: ## Remove caches, build artifacts, and temp files
	@rm -rf .pytest_cache .mypy_cache .ruff_cache dist build
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +

version: ## Show uv and Python versions
	@$(UV) --version
	@$(UV) run $(PY) -c "import platform; print('Python', platform.python_version())"
