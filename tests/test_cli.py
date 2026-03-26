from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from podcast_anything_local.cli import JobSubmissionOptions, PodcastAnythingApiClient, run_job_command
from podcast_anything_local.core.config import Settings
from podcast_anything_local.main import create_app
from podcast_anything_local.providers.rewrite.openai_compatible import (
    OpenAICompatibleRewriteProvider,
)
from podcast_anything_local.services.ingestion import IngestionService


def _build_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        app_env="test",
        app_name="Podcast Anything Local Test",
        data_dir=data_dir,
        database_path=data_dir / "app.db",
        jobs_dir=data_dir / "jobs",
        web_extractor="auto",
        rewrite_style="podcast",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="test-key",
        openai_model="gpt-4o-mini",
        tts_provider="wave",
        elevenlabs_api_key=None,
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_output_format="mp3_44100_128",
    )


def _stub_openai_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        OpenAICompatibleRewriteProvider,
        "rewrite",
        lambda self, **kwargs: "Welcome back. Today we're recording a local podcast draft.",
    )
    monkeypatch.setattr(
        OpenAICompatibleRewriteProvider,
        "generate_title",
        lambda self, **kwargs: "CLI Podcast Draft",
    )


class _TestClientSession:
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def request(self, method: str, url: str, **kwargs):
        path = urlparse(url).path
        kwargs.pop("timeout", None)
        return self._client.request(method, path, **kwargs)


def test_cli_run_job_from_url_downloads_artifacts(tmp_path: Path, monkeypatch) -> None:
    _stub_openai_provider(monkeypatch)
    def fake_ingest(self, *, source_kind=None, source_url=None, source_file_path=None, source_file_name=None):
        assert source_kind == "url"
        assert source_url == "https://example.com/article"
        return (
            "Example source material for the CLI integration test.",
            {"source_type": "webpage", "source_char_count": 52},
        )

    monkeypatch.setattr(IngestionService, "ingest", fake_ingest)

    app = create_app(_build_settings(tmp_path))
    with TestClient(app) as test_client:
        client = PodcastAnythingApiClient(
            "http://testserver",
            session=_TestClientSession(test_client),
        )
        options = JobSubmissionOptions(
            source_url="https://example.com/article",
            source_file=None,
            title=None,
            style="podcast",
            script_mode="single",
            podcast_length="medium",
            tts_provider=None,
            voice_id=None,
            voice_id_b=None,
            poll_interval=0.05,
            timeout=5,
            output_dir=tmp_path / "downloads",
            download_artifacts=True,
        )

        job, downloaded_paths = run_job_command(client, options)

        assert job["status"] == "completed"
        assert len(downloaded_paths) >= 4
        assert (tmp_path / "downloads" / job["job_id"] / "script.txt").is_file()
        assert (tmp_path / "downloads" / job["job_id"] / "audio.wav").is_file()


def test_cli_run_job_from_file_without_download(tmp_path: Path, monkeypatch) -> None:
    _stub_openai_provider(monkeypatch)
    source_file = tmp_path / "brief.txt"
    source_file.write_text("Uploaded notes for CLI file submission.", encoding="utf-8")

    app = create_app(_build_settings(tmp_path))
    with TestClient(app) as test_client:
        client = PodcastAnythingApiClient(
            "http://testserver",
            session=_TestClientSession(test_client),
        )
        options = JobSubmissionOptions(
            source_url=None,
            source_file=source_file,
            title=None,
            style="podcast",
            script_mode="single",
            podcast_length="medium",
            tts_provider=None,
            voice_id=None,
            voice_id_b=None,
            poll_interval=0.05,
            timeout=5,
            output_dir=tmp_path / "downloads",
            download_artifacts=False,
        )

        job, downloaded_paths = run_job_command(client, options)

        assert job["status"] == "completed"
        assert downloaded_paths == []
