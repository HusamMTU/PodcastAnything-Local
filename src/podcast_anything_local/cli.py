"""Small CLI client for submitting and downloading jobs through the local API."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_API_URL = os.environ.get("PODCAST_ANYTHING_API_URL", "http://127.0.0.1:8000")


class CliError(RuntimeError):
    """Raised when a CLI action fails."""


@dataclass(slots=True)
class JobSubmissionOptions:
    source_url: str | None
    source_file: Path | None
    title: str | None
    style: str
    script_mode: str
    podcast_length: str
    tts_provider: str | None
    voice_id: str | None
    voice_id_b: str | None
    poll_interval: float
    timeout: float
    output_dir: Path
    download_artifacts: bool


class PodcastAnythingApiClient:
    """HTTP client for the local Podcast Anything API."""

    def __init__(self, base_url: str, *, session: Any | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()

    def create_job(self, options: JobSubmissionOptions) -> dict[str, Any]:
        payload = {
            "title": options.title,
            "style": options.style,
            "script_mode": options.script_mode,
            "podcast_length": options.podcast_length,
            "tts_provider": options.tts_provider,
            "voice_id": options.voice_id,
            "voice_id_b": options.voice_id_b,
        }
        payload = {key: value for key, value in payload.items() if value is not None}

        if options.source_url:
            payload["source_url"] = options.source_url
            response = self._request("POST", "/jobs", json=payload, timeout=60)
            return self._read_json(response, "create job")

        assert options.source_file is not None
        with options.source_file.open("rb") as source_file:
            response = self._request(
                "POST",
                "/jobs",
                data=payload,
                files={"source_file": (options.source_file.name, source_file)},
                timeout=60,
            )
        return self._read_json(response, "create job")

    def get_job(self, job_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/jobs/{job_id}", timeout=30)
        return self._read_json(response, "read job")

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        response = self._request("GET", f"/jobs/{job_id}/artifacts", timeout=30)
        payload = self._read_json(response, "list artifacts")
        if not isinstance(payload, list):
            raise CliError("Artifact listing returned an unexpected response.")
        return payload

    def download_artifact(self, artifact_path: str, destination: Path) -> Path:
        response = self._request("GET", artifact_path, timeout=120)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output_file:
            for chunk in _iter_response_bytes(response):
                if chunk:
                    output_file.write(chunk)
        return destination

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = _resolve_url(self._base_url, path)
        try:
            response = self._session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise CliError(f"API request failed for {method} {url}: {exc}") from exc

        if getattr(response, "status_code", 500) >= 400:
            detail = _extract_response_text(response)
            raise CliError(
                f"API request failed for {method} {url} "
                f"(status={response.status_code}): {detail}"
            )
        return response

    def _read_json(self, response: Any, operation: str) -> dict[str, Any] | list[Any]:
        try:
            return response.json()
        except Exception as exc:  # pragma: no cover - defensive against unexpected client types
            raise CliError(f"Could not decode JSON response while trying to {operation}.") from exc


def run_job_command(client: PodcastAnythingApiClient, options: JobSubmissionOptions) -> tuple[dict[str, Any], list[Path]]:
    created_job = client.create_job(options)
    job_id = created_job["job_id"]

    deadline = time.monotonic() + options.timeout
    while time.monotonic() < deadline:
        job = client.get_job(job_id)
        status = job.get("status")
        if status in {"completed", "failed"}:
            break
        time.sleep(options.poll_interval)
    else:
        raise CliError(f"Timed out waiting for job {job_id} to finish.")

    if job.get("status") == "failed":
        raise CliError(f"Job {job_id} failed: {job.get('error') or 'unknown error'}")

    downloaded_paths: list[Path] = []
    if options.download_artifacts:
        artifacts = client.list_artifacts(job_id)
        destination_root = options.output_dir / job_id
        for artifact in artifacts:
            artifact_name = artifact["name"]
            download_path = artifact["download_path"]
            destination = destination_root / artifact_name
            downloaded_paths.append(client.download_artifact(download_path, destination))

    return job, downloaded_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit a job to Podcast Anything Local, wait for completion, and download artifacts.",
    )
    parser.add_argument("source", nargs="?", help="Source URL to process.")
    parser.add_argument("--source-file", default=None, help="Local input file to upload.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Base URL of the API.")
    parser.add_argument("--title", default=None, help="Optional title override.")
    parser.add_argument("--style", default="podcast", help="Rewrite style label.")
    parser.add_argument(
        "--script-mode",
        choices=["single", "duo"],
        default="single",
        help="Script mode to request.",
    )
    parser.add_argument(
        "--podcast-length",
        choices=["short", "medium", "long"],
        default="medium",
        help="Target episode length preset.",
    )
    parser.add_argument("--tts-provider", default=None, help="TTS provider override.")
    parser.add_argument("--voice-id", default=None, help="Voice override for HOST_A / single mode.")
    parser.add_argument("--voice-id-b", default=None, help="Voice override for HOST_B in duo mode.")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between job status checks.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Maximum seconds to wait for job completion.",
    )
    parser.add_argument(
        "--output-dir",
        default="downloads",
        help="Directory where downloaded artifacts will be written.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Do not download artifacts after the job completes.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.source) == bool(args.source_file):
        parser.error("Provide exactly one of a source URL or --source-file.")
    return args


def options_from_args(args: argparse.Namespace) -> JobSubmissionOptions:
    source_file = Path(args.source_file).expanduser().resolve() if args.source_file else None
    if source_file and not source_file.is_file():
        raise CliError(f"Source file not found: {source_file}")

    return JobSubmissionOptions(
        source_url=args.source,
        source_file=source_file,
        title=args.title,
        style=args.style,
        script_mode=args.script_mode,
        podcast_length=args.podcast_length,
        tts_provider=args.tts_provider,
        voice_id=args.voice_id,
        voice_id_b=args.voice_id_b,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        download_artifacts=not args.no_download,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    options = options_from_args(args)
    client = PodcastAnythingApiClient(args.api_url)

    try:
        job, downloaded_paths = run_job_command(client, options)
    except CliError as exc:
        raise SystemExit(f"error: {exc}") from exc

    print(f"job_id: {job['job_id']}")
    print(f"status: {job['status']}")
    print(f"script_mode: {job['script_mode']}")
    print(f"podcast_length: {job['podcast_length']}")
    if downloaded_paths:
        print("downloaded:")
        for path in downloaded_paths:
            print(path)


def _resolve_url(base_url: str, path: str) -> str:
    parsed = urlparse(path)
    if parsed.scheme and parsed.netloc:
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url}{path}"


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    content = getattr(response, "content", b"")
    if isinstance(content, bytes) and content:
        return content.decode("utf-8", errors="replace").strip()
    return "no error body"


def _iter_response_bytes(response: Any):
    if hasattr(response, "iter_content"):
        yield from response.iter_content(chunk_size=8192)
        return
    if hasattr(response, "iter_bytes"):
        yield from response.iter_bytes()
        return
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        yield content


if __name__ == "__main__":
    main(sys.argv[1:])
