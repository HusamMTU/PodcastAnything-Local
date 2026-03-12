PYTHON ?= python3

.PHONY: setup setup-piper download-piper-voice download-piper-duo-voices test-piper-local test-piper-local-duo test-openai-live run run-job test test-ci

setup:
	$(PYTHON) -m venv .venv
	./.venv/bin/pip install -e ".[dev]"

setup-piper:
	./.venv/bin/pip install -e ".[dev,piper]"

download-piper-voice:
	./.venv/bin/python -m piper.download_voices $${VOICE:-en_US-lessac-high} --download-dir data/piper_voices

download-piper-duo-voices:
	./.venv/bin/python -m piper.download_voices $${VOICE_A:-en_US-lessac-high} $${VOICE_B:-en_US-ryan-high} --download-dir data/piper_voices

test-piper-local:
	./.venv/bin/python scripts/test_piper_local.py

test-piper-local-duo:
	./.venv/bin/python scripts/test_piper_local.py --duo

test-openai-live:
	./.venv/bin/python scripts/test_openai_live.py $(if $(MODEL),--model $(MODEL),)

run:
	./.venv/bin/uvicorn podcast_anything_local.main:app --reload

run-job:
	./.venv/bin/python -m podcast_anything_local.cli $(ARGS)

test:
	./.venv/bin/pytest

test-ci:
	./.venv/bin/python -m compileall src tests scripts
	./.venv/bin/pytest
