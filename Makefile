PYTHON ?= python3

.PHONY: setup lint format test-openai-live test-elevenlabs-live run run-job test test-ci

setup:
	$(PYTHON) -m venv .venv
	./.venv/bin/pip install -e ".[dev]"

lint:
	./.venv/bin/ruff check .
	./.venv/bin/ruff format --check .

format:
	./.venv/bin/ruff check . --fix
	./.venv/bin/ruff format .

test-openai-live:
	./.venv/bin/python scripts/test_openai_live.py $(if $(MODEL),--model $(MODEL),)

test-elevenlabs-live:
	./.venv/bin/python scripts/test_elevenlabs_live.py $(if $(DUO),--duo,)

run:
	./.venv/bin/uvicorn podcast_anything_local.main:app --reload

run-job:
	./.venv/bin/python -m podcast_anything_local.cli $(ARGS)

test:
	./.venv/bin/pytest

test-ci:
	./.venv/bin/ruff check .
	./.venv/bin/ruff format --check .
	./.venv/bin/python -m compileall src tests scripts
	./.venv/bin/pytest
