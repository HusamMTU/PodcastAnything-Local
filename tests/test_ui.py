from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from podcast_anything_local.core.config import Settings
from podcast_anything_local.main import create_app


def _build_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        app_env="test",
        app_name="Podcast Anything Local Test",
        data_dir=data_dir,
        database_path=data_dir / "app.db",
        jobs_dir=data_dir / "jobs",
        web_extractor="auto",
        rewrite_provider="openai",
        rewrite_style="podcast",
        ollama_base_url="http://localhost:11434/api",
        ollama_model="gemma3:4b",
        ollama_generate_timeout_seconds=600,
        openai_base_url="https://api.openai.com/v1",
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        tts_provider="piper",
        tts_default_voice=None,
        tts_duo_voice=None,
        piper_model_path="./data/piper_voices/en_US-lessac-high.onnx",
        piper_model_path_b=None,
        piper_config_path="./data/piper_voices/en_US-lessac-high.onnx.json",
        piper_config_path_b=None,
        piper_speaker_id=None,
        piper_speaker_id_b=None,
        elevenlabs_api_key=None,
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_output_format="mp3_44100_128",
    )


def test_root_serves_built_in_ui(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Podcast Anything" in response.text
        assert "/ui-assets/app.js" in response.text
        assert "Podcast mode" in response.text
        assert "Title override" not in response.text
        assert 'name="title"' not in response.text
        assert 'id="job-title-value"' in response.text
        assert "health-status" not in response.text
        assert 'name="style"' not in response.text
        assert 'name="voice_id"' not in response.text
        assert 'name="voice_id_b"' not in response.text


def test_config_exposes_current_defaults(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/config")

        assert response.status_code == 200
        payload = response.json()
        assert payload["app_name"] == "Podcast Anything Local Test"
        assert payload["default_web_extractor"] == "auto"
        assert payload["default_rewrite_provider"] == "openai"
        assert payload["default_tts_provider"] == "piper"
        assert "auto" in payload["supported_web_extractors"]
        assert "bs4" in payload["supported_web_extractors"]
        assert payload["supported_rewrite_providers"][0] == "openai"
        assert "ollama" in payload["supported_rewrite_providers"]
        assert "piper" in payload["supported_tts_providers"]
        assert "demo" not in payload["supported_rewrite_providers"]
        assert "wave" not in payload["supported_tts_providers"]


def test_ui_assets_are_served(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path))
    with TestClient(app) as client:
        css_response = client.get("/ui-assets/styles.css")
        js_response = client.get("/ui-assets/app.js")

        assert css_response.status_code == 200
        assert "background" in css_response.text
        assert "height: 22rem;" in css_response.text
        assert js_response.status_code == 200
        assert "fetchJson" in js_response.text
        assert "EventSource" in js_response.text
        assert "/rewrite-preview" in js_response.text
        assert "loadHealth" not in js_response.text
        assert 'voice_id' not in js_response.text
        assert 'voice_id_b' not in js_response.text
