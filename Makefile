.DEFAULT_GOAL := help

.PHONY: help setup run test test-python test-worker lint repository-check check container demo audit

help:
	@echo "setup             Install locked Python and Node dependencies"
	@echo "run               Start the workbench on port 8501"
	@echo "check             Run all offline quality checks"
	@echo "test              Run Python and Worker tests"
	@echo "lint              Check Python syntax and correctness rules"
	@echo "repository-check  Check docs, generated assets and published evidence"
	@echo "container         Build and start the saved-evidence container"
	@echo "demo              Start the optional Cloudflare browser demo"
	@echo "audit             Query dependency advisories (online; findings fail)"

setup:
	uv sync --locked --extra dev
	npm ci

run:
	uv run --locked streamlit run streamlit_app/app.py

test: test-python test-worker

test-python:
	uv run --locked --extra dev pytest -q

test-worker:
	npm run test:worker

lint:
	uv run --locked --extra dev ruff check .

repository-check:
	uv run --locked python scripts/check_repository.py

check: lint test repository-check

container:
	docker compose up --build --wait

demo:
	npm run demo

audit:
	uv run --locked python scripts/audit_dependencies.py
