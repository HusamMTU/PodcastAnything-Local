from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from podcast_anything_local.core.config import Settings
from podcast_anything_local.providers.tts.base import SynthesizedAudio
from podcast_anything_local.services.audio import (
    AudioService,
    _parse_duo_turns,
    _sanitize_single_host_script,
)


class _CapturingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str | None]] = []

    def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
    ) -> SynthesizedAudio:
        self.calls.append((text, voice_id, speaker))
        return SynthesizedAudio(
            data=b"RIFFfakeWAVE",
            file_name="audio.wav",
            content_type="audio/wav",
        )

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        return segments[0]


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
        tts_provider="wave",
        tts_default_voice="host_a",
        tts_duo_voice="host_b",
        piper_model_path=None,
        piper_model_path_b=None,
        piper_config_path=None,
        piper_config_path_b=None,
        piper_speaker_id=None,
        piper_speaker_id_b=None,
        elevenlabs_api_key=None,
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_output_format="mp3_44100_128",
    )


def test_sanitize_single_host_script_strips_headings_and_cues() -> None:
    script = """
**Intro (0:00-0:30)**

[Upbeat music fades in]

**Host:**
Welcome back. [Music fades out] Today we're talking about quantum mechanics.
"""

    cleaned = _sanitize_single_host_script(script)

    assert cleaned == "Welcome back. Today we're talking about quantum mechanics."


def test_parse_duo_turns_ignores_stage_directions_and_markdown() -> None:
    script = """
**Intro (0:00-0:30)**

[Upbeat music fades in]

**HOST_A:** Welcome back.
HOST_B: Glad to be here.
[Transition sting]
HOST_A: Today we're talking about quantum mechanics.
"""

    assert _parse_duo_turns(script) == [
        ("HOST_A", "Welcome back."),
        ("HOST_B", "Glad to be here."),
        ("HOST_A", "Today we're talking about quantum mechanics."),
    ]


def test_parse_duo_turns_strips_literal_host_placeholders_from_spoken_text() -> None:
    script = """
HOST_A: I'm your host HOST_A. And joining me today is HOST_B,
HOST_B: Thanks, HOST_A. Happy to be here.
HOST_A: HOST_B, let's get into it.
"""

    assert _parse_duo_turns(script) == [
        ("HOST_A", "I'm your host. And joining me today is my co-host,"),
        ("HOST_B", "Thanks, my co-host. Happy to be here."),
        ("HOST_A", "my co-host, let's get into it."),
    ]


def test_audio_service_sanitizes_single_host_text_before_tts(tmp_path: Path, monkeypatch) -> None:
    provider = _CapturingProvider()
    service = AudioService(_build_settings(tmp_path))
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)

    service.synthesize(
        script_text="""
**Intro (0:00-0:30)**
[Upbeat music fades in]
Host: Welcome back. [Music fades out] Today we're talking about quantum mechanics.
""",
        script_mode="single",
        provider_name="wave",
        voice_id=None,
        voice_id_b=None,
    )

    assert provider.calls == [
        (
            "Welcome back. Today we're talking about quantum mechanics.",
            "host_a",
            "host_a",
        )
    ]


def test_audio_service_does_not_apply_single_host_default_voice_to_duo(tmp_path: Path, monkeypatch) -> None:
    provider = _CapturingProvider()
    service = AudioService(_build_settings(tmp_path))
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)

    service.synthesize(
        script_text="""
HOST_A: Welcome back.
HOST_B: Glad to be here.
""",
        script_mode="duo",
        provider_name="piper",
        voice_id=None,
        voice_id_b=None,
    )

    assert provider.calls == [
        ("Welcome back.", None, "host_a"),
        ("Glad to be here.", "host_b", "host_b"),
    ]


def test_audio_service_uses_openai_voice_defaults_without_piper_model_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = _build_settings(tmp_path)
    settings = replace(
        settings,
        tts_provider="openai",
        tts_default_voice="./data/piper_voices/en_US-ryan-high.onnx",
        openai_tts_voice="marin",
        openai_tts_voice_b="cedar",
    )
    service = AudioService(settings)
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)

    service.synthesize(
        script_text="""
HOST_A: Welcome back.
HOST_B: Glad to be here.
""",
        script_mode="duo",
        provider_name="openai",
        voice_id=None,
        voice_id_b=None,
    )

    assert provider.calls == [
        ("Welcome back.", "marin", "host_a"),
        ("Glad to be here.", "cedar", "host_b"),
    ]
