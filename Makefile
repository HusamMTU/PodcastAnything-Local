PYTHON ?= python3
IMAGE ?= podcast-anything-local:dev

.PHONY: setup lint format test-openai-live test-elevenlabs-live run run-job test test-ci docker-build docker-run

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

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 8000:8000 --env-file .env -v "$(PWD)/data:/app/data" $(IMAGE)
