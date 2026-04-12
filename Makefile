.PHONY: install test run lint format typecheck clean help

# Default target: help
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install    Setup dependencies using uv"
	@echo "  run        Start the bot locally"
	@echo "  test       Run tests using pytest"
	@echo "  lint       Run ruff check"
	@echo "  format     Run ruff format"
	@echo "  typecheck  Run ty check"
	@echo "  clean      Remove caches and virtualenv"

install:
	uv sync
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; fi

run:
	uv run harry

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run ty check

clean:
	rm -rf .venv .pytest_cache .ruff_cache __pycache__ .pybaseball_cache
