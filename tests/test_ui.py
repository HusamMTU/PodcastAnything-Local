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
        rewrite_style="podcast",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        tts_provider="openai",
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
        assert 'class="workspace-title"' in response.text
        assert "/ui-assets/app.js" in response.text
        assert ">Sources</h2>" in response.text
        assert ">Episode</h2>" in response.text
        assert ">Studio</h2>" in response.text
        assert "Audio generator" in response.text
        assert 'class="panel-view-switch"' in response.text
        assert 'data-sources-view="new"' in response.text
        assert 'data-sources-view="history"' in response.text
        assert "Podcast mode" in response.text
        assert 'data-source-mode="text"' in response.text
        assert 'name="source_text"' in response.text
        assert 'accept=".txt,.pdf,.docx,.pptx"' in response.text
        assert 'id="workspace-grid" class="workspace-grid studio-collapsed"' in response.text
        assert 'id="sources-panel" class="panel workspace-panel side-panel sources-panel"' in response.text
        assert 'class="panel workspace-panel episode-panel"' in response.text
        assert 'id="studio-panel" class="panel workspace-panel side-panel studio-panel is-collapsed"' in response.text
        assert 'id="sources-collapse"' in response.text
        assert 'id="sources-expand"' in response.text
        assert 'id="studio-collapse"' in response.text
        assert 'id="studio-expand"' in response.text
        assert 'id="provider-summary"' not in response.text
        assert "Build a grounded podcast draft" not in response.text
        assert 'class="compact-icon compact-icon-right"' in response.text
        assert 'class="compact-icon compact-icon-left"' in response.text
        assert "Sources</span>" not in response.text
        assert "Studio</span>" not in response.text
        assert "Nothing loaded yet" not in response.text
        assert "Current settings" not in response.text
        assert "Selected settings" not in response.text
        assert "Select a source, then reopen earlier jobs from history." not in response.text
        assert "Start a fresh episode from a link, file, or pasted text." not in response.text
        assert "Listen to the latest generated pass." not in response.text
        assert "No audio loaded yet." not in response.text
        assert "This panel updates as the job progresses." not in response.text
        assert '<details class="content-card artifact-card-collapsible">' in response.text
        assert 'id="settings-mode-summary"' in response.text
        assert 'id="settings-voice-summary"' in response.text
        assert 'id="job-script-mode"' not in response.text
        assert 'id="job-providers"' not in response.text
        assert 'id="retry-button"' in response.text
        assert 'id="refresh-job-button"' not in response.text
        assert 'id="job-id"' not in response.text
        assert 'id="job-status-badge"' not in response.text
        assert 'id="job-source-kind"' not in response.text
        assert 'name="rewrite_provider"' not in response.text
        assert "Title override" not in response.text
        assert "Episode title" not in response.text
        assert 'name="title"' not in response.text
        assert 'id="job-title-shell"' in response.text
        assert 'id="job-title-value"' in response.text
        assert 'class="audio-overview-title-shell is-hidden"' in response.text
        assert "Generating title..." not in response.text
        assert 'id="audio-download"' in response.text
        assert 'id="script-download"' in response.text
        assert 'aria-label="Download audio overview"' in response.text
        assert 'aria-label="Download draft script"' in response.text
        assert 'class="corner-action-link inline-link is-hidden"' in response.text
        assert "Download</a>" not in response.text
        assert 'id="script-preview" class="script-preview"' in response.text
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
        assert payload["script_writer"] == "openai"
        assert payload["default_tts_provider"] == "openai"
        assert "auto" in payload["supported_web_extractors"]
        assert "bs4" in payload["supported_web_extractors"]
        assert "openai" in payload["supported_tts_providers"]
        assert "wave" not in payload["supported_tts_providers"]


def test_ui_assets_are_served(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path))
    with TestClient(app) as client:
        css_response = client.get("/ui-assets/styles.css")
        js_response = client.get("/ui-assets/app.js")

        assert css_response.status_code == 200
        assert "background" in css_response.text
        assert ".workspace-title" in css_response.text
        assert ".workspace-grid" in css_response.text
        assert "grid-template-columns: var(--sources-width) var(--episode-width) var(--studio-width);" in css_response.text
        assert "--side-panel-collapsed-width: 4.75rem;" in css_response.text
        assert "--episode-panel-width: minmax(0, 2fr);" in css_response.text
        assert ".workspace-grid.studio-collapsed" in css_response.text
        assert ".workspace-panel" in css_response.text
        assert ".job-details" in css_response.text
        assert ".side-panel.is-collapsed .side-panel-compact" in css_response.text
        assert ".compact-icon" in css_response.text
        assert ".toggle-icon" in css_response.text
        assert "flex-direction: column;" in css_response.text
        assert "justify-content: flex-start;" in css_response.text
        assert ".panel-view-switch" in css_response.text
        assert ".panel-view-button" in css_response.text
        assert ".studio-summary" in css_response.text
        assert ".episode-top" in css_response.text
        assert "--panel-height: min(86vh, 64rem);" in css_response.text
        assert "max-height: var(--panel-height);" in css_response.text
        assert ".audio-overview-title-shell" in css_response.text
        assert ".audio-overview-title-shell.is-hidden" in css_response.text
        assert ".audio-overview-title" in css_response.text
        assert ".audio-stage-pill" in css_response.text
        assert ".corner-action-link" in css_response.text
        assert ".corner-action-icon" in css_response.text
        assert ".script-card" in css_response.text
        assert "flex: 1;" in css_response.text
        assert ".script-preview" in css_response.text
        assert "min-height: 0;" in css_response.text
        assert ".script-turn" in css_response.text
        assert ".source-textarea" in css_response.text
        assert ".studio-settings-grid label" in css_response.text
        assert ".artifact-card-collapsible" in css_response.text
        assert ".artifact-summary::after" in css_response.text
        assert ".artifact-list" in css_response.text
        assert "max-height: 16rem;" in css_response.text
        assert "grid-template-columns: 1fr;" in css_response.text
        assert "--content-width: 120rem;" in css_response.text
        assert ".form-span-full" in css_response.text
        assert ".recent-jobs" in css_response.text
        assert "scrollbar-gutter: stable;" in css_response.text
        assert js_response.status_code == 200
        assert "fetchJson" in js_response.text
        assert 'source_text' in js_response.text
        assert "syncSelectedSettingsSummary" in js_response.text
        assert "setSourcesView" in js_response.text
        assert "renderScriptPreview" in js_response.text
        assert "createScriptTurn" in js_response.text
        assert "shouldLoadArtifacts" in js_response.text
        assert '["rewriting", "synthesizing"].includes(job.current_stage || "")' in js_response.text
        assert "jobTitleShell" in js_response.text
        assert "Generating title..." not in js_response.text
        assert "setPanelCollapsed" in js_response.text
        assert "applyPanelState" in js_response.text
        assert "providerSummary" not in js_response.text
        assert "loadHealth" not in js_response.text
        assert 'voice_id' not in js_response.text
        assert 'voice_id_b' not in js_response.text
