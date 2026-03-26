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
        self.dialogue_calls: list[tuple[list[tuple[str, str]], str | None, str | None]] = []
        self.stream_calls: list[tuple[str, str | None, str | None]] = []
        self.stream_dialogue_calls: list[tuple[list[tuple[str, str]], str | None, str | None]] = []

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

    def synthesize_dialogue(
        self,
        *,
        turns: list[tuple[str, str]],
        voice_id_a: str | None,
        voice_id_b: str | None,
    ) -> SynthesizedAudio:
        self.dialogue_calls.append((turns, voice_id_a, voice_id_b))
        return SynthesizedAudio(
            data=b"ID3fake",
            file_name="audio.mp3",
            content_type="audio/mpeg",
        )

    def supports_live_streaming(self) -> bool:
        return True

    def live_stream_content_type(self) -> str:
        return "audio/mpeg"

    def live_stream_file_name(self) -> str:
        return "audio.mp3"

    def stream_synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
        on_chunk,
    ) -> SynthesizedAudio:
        self.stream_calls.append((text, voice_id, speaker))
        on_chunk(b"chunk-a")
        on_chunk(b"chunk-b")
        return SynthesizedAudio(
            data=b"chunk-achunk-b",
            file_name="audio.mp3",
            content_type="audio/mpeg",
        )

    def stream_synthesize_dialogue(
        self,
        *,
        turns: list[tuple[str, str]],
        voice_id_a: str | None,
        voice_id_b: str | None,
        on_chunk,
    ) -> SynthesizedAudio:
        self.stream_dialogue_calls.append((turns, voice_id_a, voice_id_b))
        on_chunk(b"dialogue-a")
        on_chunk(b"dialogue-b")
        return SynthesizedAudio(
            data=b"dialogue-adialogue-b",
            file_name="audio.mp3",
            content_type="audio/mpeg",
        )


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
        elevenlabs_api_key=None,
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_dialogue_model_id="eleven_v3",
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


def test_audio_service_uses_openai_voice_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = _build_settings(tmp_path)
    settings = replace(
        settings,
        tts_provider="openai",
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


def test_audio_service_emits_preview_segments_for_openai_duo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = replace(
        _build_settings(tmp_path),
        tts_provider="openai",
        openai_tts_voice="marin",
        openai_tts_voice_b="cedar",
    )
    service = AudioService(settings)
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)
    previews: list[tuple[bytes, int]] = []

    audio = service.synthesize(
        script_text="HOST_A: Welcome back.\nHOST_B: Glad to be here.",
        script_mode="duo",
        provider_name="openai",
        voice_id=None,
        voice_id_b=None,
        on_preview_segment=lambda segment, index: previews.append((segment.data, index)),
    )

    assert provider.calls == [
        ("Welcome back.", "marin", "host_a"),
        ("Glad to be here.", "cedar", "host_b"),
    ]
    assert previews == [
        (b"RIFFfakeWAVE", 1),
        (b"RIFFfakeWAVE", 2),
    ]
    assert audio.file_name == "audio.wav"


def test_audio_service_emits_openai_duo_preview_segments_before_join(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _PreviewAwareProvider(_CapturingProvider):
        def __init__(self) -> None:
            super().__init__()
            self.preview_count = 0

        def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
            assert self.preview_count == len(segments)
            return segments[0]

    provider = _PreviewAwareProvider()
    settings = replace(
        _build_settings(tmp_path),
        tts_provider="openai",
        openai_tts_voice="marin",
        openai_tts_voice_b="cedar",
    )
    service = AudioService(settings)
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)

    service.synthesize(
        script_text="HOST_A: Welcome back.\nHOST_B: Glad to be here.",
        script_mode="duo",
        provider_name="openai",
        voice_id=None,
        voice_id_b=None,
        on_preview_segment=lambda segment, index: setattr(provider, "preview_count", index),
    )


def test_audio_service_uses_elevenlabs_voice_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = _build_settings(tmp_path)
    settings = replace(
        settings,
        tts_provider="elevenlabs",
        elevenlabs_voice_id="voice-a",
        elevenlabs_voice_id_b="voice-b",
    )
    service = AudioService(settings)
    monkeypatch.setattr(
        "podcast_anything_local.services.audio.ElevenLabsTTSProvider",
        lambda **kwargs: provider,
    )

    audio = service.synthesize(
        script_text="""
HOST_A: Welcome back.
HOST_B: Glad to be here.
""",
        script_mode="duo",
        provider_name="elevenlabs",
        voice_id=None,
        voice_id_b=None,
    )

    assert provider.calls == []
    assert provider.dialogue_calls == [
        (
            [("HOST_A", "Welcome back."), ("HOST_B", "Glad to be here.")],
            "voice-a",
            "voice-b",
        )
    ]
    assert audio.file_name == "audio.mp3"


def test_audio_service_streams_elevenlabs_single_when_callbacks_are_provided(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = replace(
        _build_settings(tmp_path),
        tts_provider="elevenlabs",
        elevenlabs_voice_id="voice-a",
    )
    service = AudioService(settings)
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)
    started: list[tuple[str, str]] = []
    chunks: list[bytes] = []

    audio = service.synthesize(
        script_text="Host: Welcome back.",
        script_mode="single",
        provider_name="elevenlabs",
        voice_id=None,
        voice_id_b=None,
        on_stream_start=lambda content_type, file_name: started.append((content_type, file_name)),
        on_stream_chunk=chunks.append,
    )

    assert provider.calls == []
    assert provider.stream_calls == [("Welcome back.", "voice-a", "host_a")]
    assert started == [("audio/mpeg", "audio.mp3")]
    assert chunks == [b"chunk-a", b"chunk-b"]
    assert audio.file_name == "audio.mp3"


def test_audio_service_streams_openai_single_when_callbacks_are_provided(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = replace(
        _build_settings(tmp_path),
        tts_provider="openai",
        openai_tts_voice="marin",
    )
    service = AudioService(settings)
    monkeypatch.setattr(service, "_build_provider", lambda provider_name: provider)
    started: list[tuple[str, str]] = []
    chunks: list[bytes] = []

    audio = service.synthesize(
        script_text="Host: Welcome back.",
        script_mode="single",
        provider_name="openai",
        voice_id=None,
        voice_id_b=None,
        on_stream_start=lambda content_type, file_name: started.append((content_type, file_name)),
        on_stream_chunk=chunks.append,
    )

    assert provider.calls == []
    assert provider.stream_calls == [("Welcome back.", "marin", "host_a")]
    assert started == [("audio/mpeg", "audio.mp3")]
    assert chunks == [b"chunk-a", b"chunk-b"]
    assert audio.file_name == "audio.mp3"


def test_audio_service_streams_elevenlabs_duo_when_callbacks_are_provided(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CapturingProvider()
    settings = replace(
        _build_settings(tmp_path),
        tts_provider="elevenlabs",
        elevenlabs_voice_id="voice-a",
        elevenlabs_voice_id_b="voice-b",
    )
    service = AudioService(settings)
    monkeypatch.setattr(
        "podcast_anything_local.services.audio.ElevenLabsTTSProvider",
        lambda **kwargs: provider,
    )
    started: list[tuple[str, str]] = []
    chunks: list[bytes] = []

    audio = service.synthesize(
        script_text="HOST_A: Welcome back.\nHOST_B: Glad to be here.",
        script_mode="duo",
        provider_name="elevenlabs",
        voice_id=None,
        voice_id_b=None,
        on_stream_start=lambda content_type, file_name: started.append((content_type, file_name)),
        on_stream_chunk=chunks.append,
    )

    assert provider.dialogue_calls == []
    assert provider.stream_dialogue_calls == [
        ([("HOST_A", "Welcome back."), ("HOST_B", "Glad to be here.")], "voice-a", "voice-b")
    ]
    assert started == [("audio/mpeg", "audio.mp3")]
    assert chunks == [b"dialogue-a", b"dialogue-b"]
    assert audio.file_name == "audio.mp3"
