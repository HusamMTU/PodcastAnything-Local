PYTHON ?= python3

.PHONY: setup setup-piper setup-ollama start-ollama-mac download-piper-voice download-piper-duo-voices pull-ollama-model test-piper-local test-piper-local-duo test-ollama-local test-openai-live run run-job test test-ci

setup:
	$(PYTHON) -m venv .venv
	./.venv/bin/pip install -e ".[dev]"

setup-piper:
	./.venv/bin/pip install -e ".[dev,piper]"

setup-ollama:
	./.venv/bin/python scripts/test_ollama_local.py --check-only $(if $(MODEL),--model $(MODEL),)

start-ollama-mac:
	open -a /Applications/Ollama.app --args hidden

download-piper-voice:
	./.venv/bin/python -m piper.download_voices $${VOICE:-en_US-lessac-high} --download-dir data/piper_voices

download-piper-duo-voices:
	./.venv/bin/python -m piper.download_voices $${VOICE_A:-en_US-lessac-high} $${VOICE_B:-en_US-ryan-high} --download-dir data/piper_voices

pull-ollama-model:
	./.venv/bin/python scripts/test_ollama_local.py --check-only --pull-if-missing $(if $(MODEL),--model $(MODEL),)

test-piper-local:
	./.venv/bin/python scripts/test_piper_local.py

test-piper-local-duo:
	./.venv/bin/python scripts/test_piper_local.py --duo

test-ollama-local:
	./.venv/bin/python scripts/test_ollama_local.py --pull-if-missing $(if $(MODEL),--model $(MODEL),)

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
