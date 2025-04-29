.PHONY: format install run

format:
	ruff format ./src
	ruff check ./src --fix

install:
	@command -v uv >/dev/null 2>&1 || pip install uv
	uv sync

run:
	uv run src/main.py

run-docker:
	docker compose up -d