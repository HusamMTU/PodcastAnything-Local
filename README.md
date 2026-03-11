# Podcast Anything Local

Local-first backend for turning a webpage URL, YouTube URL, or uploaded
document into:

- a rewritten podcast script
- a synthesized audio file

The recommended path in this repo is a real local run with:

- `ollama` for script rewriting
- `piper` for speech synthesis

Supported inputs:

- webpage URL
- YouTube URL
- uploaded `.txt`, `.pdf`, or `.docx`

## What You Get

Each completed job stores its original artifacts under `data/jobs/<job_id>/`.
Typical outputs are:

- `source.txt`
- `metadata.json`
- `script.txt`
- `audio.wav`

If you use the API directly, that is the storage location you work with. If you
use the CLI, it can also download copies into a separate local folder such as
`downloads/<job_id>/`.

## Quick Start

This path is for a real local end-to-end run with local models and real output
files.

### 1. Base setup

```bash
make setup
cp .env.example .env
```

`.env.example` is already set up for the recommended local stack:

- `REWRITE_PROVIDER=ollama`
- `TTS_PROVIDER=piper`

### 2. Install Piper and download a voice

```bash
make setup-piper
make download-piper-duo-voices
make test-piper-local
make test-piper-local-duo
```

### 3. Start Ollama and pull a model

On macOS in this workspace:

```bash
make start-ollama-mac
make setup-ollama MODEL=gemma3:4b
make pull-ollama-model MODEL=gemma3:4b
make test-ollama-local MODEL=gemma3:4b
```

If you are not on macOS, start Ollama using the normal method for your platform
and keep `OLLAMA_BASE_URL` pointed at the running local API.

### 4. Start the API and UI

```bash
make run
```

Useful local URLs:

- UI: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`
- healthcheck: `http://127.0.0.1:8000/health`

### 5. Run a job from the UI

Open `http://127.0.0.1:8000/` and:

- choose URL or Upload
- submit a source
- watch the job status
- see the rewrite stream live in the script preview for Ollama-backed jobs
- preview the generated script
- play or download the generated audio

The UI works against the same local API and the same job storage.

By default, the rewrite step now targets about 2-4 minutes of audio output
instead of a longer podcast episode.

### 6. Optional: run a job from the CLI and download the outputs

```bash
make run-job ARGS="https://example.com/article --output-dir ./downloads"
```

Or submit a local file:

```bash
make run-job ARGS="--source-file ./brief.txt --output-dir ./downloads"
```

Expected result:

- the job finishes with `status: completed`
- canonical artifacts exist under `data/jobs/<job_id>/`
- the CLI downloads copies under `downloads/<job_id>/`
- the output folder includes `script.txt` and `audio.wav`

## Day-To-Day Usage

### CLI

The built-in web UI at `http://127.0.0.1:8000/` is the easiest way to use the
app interactively. The CLI is useful for quick runs and scripting.

Submit a URL, wait for completion, and download artifacts:

```bash
make run-job ARGS="https://example.com/article --output-dir ./downloads"
```

Submit a local file:

```bash
make run-job ARGS="--source-file ./brief.txt --output-dir ./downloads"
```

Direct module invocation also works:

```bash
./.venv/bin/python -m podcast_anything_local.cli \
  --source-file ./brief.txt \
  --script-mode single \
  --output-dir ./downloads
```

Useful CLI flags:

- `--script-mode single`
- `--script-mode duo`
- `--voice-id <speaker_id>`
- `--voice-id-b <speaker_id>`
- `--output-dir ./downloads`
- `--no-download`

By default, the CLI downloads copies of the completed job files into
`--output-dir/<job_id>/` such as `downloads/<job_id>/`. If you pass
`--no-download`, the job still runs, but no copies are downloaded. The original
job files remain under `data/jobs/<job_id>/`.

### API

Available endpoints:

- `GET /health`
- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/rewrite-stream`
- `GET /jobs/{job_id}/artifacts`
- `GET /jobs/{job_id}/artifacts/{artifact_name}`
- `POST /jobs/{job_id}/retry`

Create a job from a URL:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://example.com/article",
    "script_mode": "single"
  }'
```

Create a job from a file upload:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -F source_file=@./brief.txt \
  -F script_mode=single
```

List a job's artifacts:

```bash
curl http://127.0.0.1:8000/jobs/<job_id>/artifacts
```

Download one artifact:

```bash
curl -L http://127.0.0.1:8000/jobs/<job_id>/artifacts/script.txt -o script.txt
```

## Configuration

The app loads `.env` automatically on startup.

The recommended local configuration is:

```bash
WEB_EXTRACTOR=auto
REWRITE_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/api
OLLAMA_MODEL=gemma3:4b
OLLAMA_GENERATE_TIMEOUT_SECONDS=600

TTS_PROVIDER=piper
PIPER_MODEL_PATH=./data/piper_voices/en_US-lessac-high.onnx
PIPER_CONFIG_PATH=./data/piper_voices/en_US-lessac-high.onnx.json
PIPER_MODEL_PATH_B=./data/piper_voices/en_US-ryan-high.onnx
PIPER_CONFIG_PATH_B=./data/piper_voices/en_US-ryan-high.onnx.json
PIPER_SPEAKER_ID=
PIPER_SPEAKER_ID_B=
```

In this recommended duo setup, `HOST_A` uses `lessac-high` and `HOST_B` uses
`ryan-high`.

Most important settings:

- `WEB_EXTRACTOR`
- `REWRITE_PROVIDER`
- `TTS_PROVIDER`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_GENERATE_TIMEOUT_SECONDS`
- `PIPER_MODEL_PATH`
- `PIPER_CONFIG_PATH`
- `DATA_DIR`

If you want hosted providers instead of local ones:

- set `REWRITE_PROVIDER=openai` and fill in `OPENAI_API_KEY`
- set `TTS_PROVIDER=elevenlabs` and fill in `ELEVENLABS_API_KEY`

If you are using a local rewrite model on a limited machine such as a laptop or
a small server, it is generally recommended to stay at or under roughly `9B`
parameters. Larger local models can become too slow or unreliable for this
workflow. If you need more capable rewriting than a local `<= 9B` model can
deliver, especially for `duo` mode, `REWRITE_PROVIDER=openai` is the
recommended path.

## Notes

- `WEB_EXTRACTOR=auto` tries `trafilatura` first and falls back to `bs4`
- `WEB_EXTRACTOR=trafilatura` forces article extraction through `trafilatura`
- `WEB_EXTRACTOR=bs4` forces the simpler BeautifulSoup paragraph extractor
- for Ollama rewrite jobs, the built-in UI opens a live SSE stream so the
  script preview updates while the rewrite is still generating
- `make setup-ollama` checks whether the local Ollama API is reachable and
  whether the configured model exists
- `make pull-ollama-model` asks the local Ollama service to download the model
- `make test-ollama-local` writes a sample rewrite through the project provider
- rewritten scripts are targeted to about 2-4 minutes of spoken audio and are
  capped to an approximate spoken-word budget before TTS
- if Ollama is slow on your machine, increase `OLLAMA_GENERATE_TIMEOUT_SECONDS`
  in `.env`
- `make test-piper-local` writes a sample WAV through the project provider
- `make test-piper-local-duo` writes a two-host WAV using `PIPER_MODEL_PATH` for
  `HOST_A` and `PIPER_MODEL_PATH_B` for `HOST_B`
- for file uploads, send `multipart/form-data`
- for URL submissions, use JSON or form data, but provide exactly one of
  `source_url` or `source_file`

## Development

Run the test suite:

```bash
make test
```

Verified locally:

- `make test`
- `make test-piper-local`
- `make test-ollama-local MODEL=gemma3:4b`

Development-only fallback providers still exist for testing and bring-up:

- rewrite: `demo`
- TTS: `wave`

They are not the recommended path for actual output generation.

## Troubleshooting

- If `make run` fails, make sure you ran `make setup` first.
- If `.env` changes are not reflected, restart the API process.
- If `make test-piper-local` fails, check that the Piper voice files exist under
  `data/piper_voices/`.
- If `make setup-ollama` or `make test-ollama-local` fails, confirm Ollama is
  running and serving `OLLAMA_BASE_URL`.
