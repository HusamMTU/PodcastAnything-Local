from __future__ import annotations

from pathlib import Path

from podcast_anything_local.core.config import Settings
from podcast_anything_local.providers.rewrite.base import RewriteProviderError
from podcast_anything_local.providers.rewrite.prompting import (
    MAX_SPOKEN_WORDS,
    get_podcast_length_target,
)
from podcast_anything_local.services.rewrite import RewriteService


class _FakeProvider:
    def __init__(self, response: str, title_response: str = "Generated Title") -> None:
        self._response = response
        self._title_response = title_response

    def rewrite(
        self,
        *,
        source_text: str,
        title: str | None = None,
        style: str = "podcast",
        source_type: str | None = None,
        script_mode: str = "single",
        podcast_length: str = "medium",
    ) -> str:
        return self._response

    def generate_title(
        self,
        *,
        script_text: str,
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        return self._title_response


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


def test_rewrite_service_normalizes_common_duo_labels(tmp_path: Path, monkeypatch) -> None:
    service = RewriteService(_build_settings(tmp_path))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(
            """
**Host:** Welcome back.
**Co-host:** Glad to be here.
Host: Today we're talking quantum mechanics.
Co-host: Let's get into it.
"""
        ),
    )

    result = service.rewrite(
        source_text="Source text",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="duo",
        podcast_length="medium",
    )

    assert result == (
        "HOST_A: Welcome back.\n"
        "HOST_B: Glad to be here.\n"
        "HOST_A: Today we're talking quantum mechanics.\n"
        "HOST_B: Let's get into it."
    )


def test_rewrite_service_normalizes_named_speakers(tmp_path: Path, monkeypatch) -> None:
    service = RewriteService(_build_settings(tmp_path))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(
            """
Intro: cold open
Alice: Welcome back.
Bob: Glad to be here.
Alice: Today we're talking quantum mechanics.
Bob: Let's start with the photoelectric effect.
"""
        ),
    )

    result = service.rewrite(
        source_text="Source text",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="duo",
        podcast_length="medium",
    )

    assert result == (
        "HOST_A: Welcome back.\n"
        "HOST_B: Glad to be here.\n"
        "HOST_A: Today we're talking quantum mechanics.\n"
        "HOST_B: Let's start with the photoelectric effect."
    )


def test_rewrite_service_errors_early_for_unparseable_duo_output(tmp_path: Path, monkeypatch) -> None:
    service = RewriteService(_build_settings(tmp_path))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider("This is a monologue instead of a duo script."),
    )

    try:
        service.rewrite(
            source_text="Source text",
            title="Title",
            style="podcast",
            source_type="text",
            script_mode="duo",
            podcast_length="medium",
        )
    except RewriteProviderError as exc:
        assert "recognizable speaker turns" in str(exc)
    else:
        raise AssertionError("Expected RewriteProviderError")


def test_rewrite_service_rejects_duo_output_with_too_few_real_turns(
    tmp_path: Path, monkeypatch
) -> None:
    service = RewriteService(_build_settings(tmp_path))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(
            """
HOST_A: Let me set the stage.
HOST_B: Great, now here is a detailed outline.

---

1. Background
- Bullet point one
- Bullet point two
"""
        ),
    )

    try:
        service.rewrite(
            source_text="Source text",
            title="Title",
            style="podcast",
            source_type="text",
            script_mode="duo",
            podcast_length="medium",
        )
    except RewriteProviderError as exc:
        assert "enough distinct speaker turns" in str(exc)
    else:
        raise AssertionError("Expected RewriteProviderError")


def test_prepare_source_text_removes_citations_tables_and_reference_section(tmp_path: Path) -> None:
    service = RewriteService(_build_settings(tmp_path))

    prepared, metadata = service.prepare_source_text(
        source_text="""
Quantum mechanics explains atomic behavior.[1][2]

| Year | Scientist |
|------|-----------|
| 1900 | Planck |

Wave-particle duality matters for modern physics.[9]

References
This line should never be included.
""",
        script_mode="duo",
    )

    assert prepared == (
        "Quantum mechanics explains atomic behavior.\n\n"
        "Wave-particle duality matters for modern physics."
    )
    assert metadata == {
        "rewrite_input_char_count": len(prepared),
        "rewrite_input_truncated": False,
    }


def test_prepare_source_text_truncates_long_duo_input(tmp_path: Path) -> None:
    service = RewriteService(_build_settings(tmp_path))
    source_text = "\n\n".join(
        (
            f"Section {index}: Quantum mechanics explains how microscopic systems behave in ways "
            "that classical physics cannot fully describe. "
        )
        * 12
        for index in range(20)
    )

    prepared, metadata = service.prepare_source_text(
        source_text=source_text,
        script_mode="duo",
    )

    assert len(prepared) <= 12_000
    assert metadata["rewrite_input_char_count"] == len(prepared)
    assert metadata["rewrite_input_truncated"] is True


def test_rewrite_service_truncates_long_single_script_to_target_duration(
    tmp_path: Path, monkeypatch
) -> None:
    service = RewriteService(_build_settings(tmp_path))
    long_sentence = (
        "Quantum mechanics changed physics by showing that microscopic systems follow "
        "probabilistic rules rather than classical certainty. "
    )
    long_script = "\n\n".join(long_sentence * 10 for _ in range(12))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(long_script),
    )

    result = service.rewrite(
        source_text="Source text",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="single",
        podcast_length="medium",
    )

    assert len(result.split()) <= MAX_SPOKEN_WORDS + 5
    assert result.endswith((".", "!", "?"))


def test_rewrite_service_truncates_long_duo_script_to_target_duration(
    tmp_path: Path, monkeypatch
) -> None:
    service = RewriteService(_build_settings(tmp_path))
    host_a_line = (
        "HOST_A: Quantum mechanics changed physics by showing that microscopic systems follow "
        "probabilistic rules rather than classical certainty and by forcing scientists to "
        "rethink matter, energy, and measurement.\n"
    )
    host_b_line = (
        "HOST_B: That shift led to modern electronics, lasers, and computing, and it also "
        "changed how we talk about certainty, observation, and the limits of prediction.\n"
    )
    long_script = (host_a_line + host_b_line) * 12
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(long_script),
    )

    result = service.rewrite(
        source_text="Source text",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="duo",
        podcast_length="medium",
    )

    spoken_words = [
        word
        for word in result.replace("HOST_A:", "").replace("HOST_B:", "").split()
        if word
    ]
    assert len(spoken_words) <= MAX_SPOKEN_WORDS + 5
    assert result.startswith("HOST_A:")


def test_rewrite_service_uses_podcast_length_preset_for_word_budget(
    tmp_path: Path, monkeypatch
) -> None:
    service = RewriteService(_build_settings(tmp_path))
    long_sentence = (
        "Quantum mechanics changed physics by showing that microscopic systems follow "
        "probabilistic rules rather than classical certainty and by reshaping modern "
        "electronics, chemistry, and computing. "
    )
    long_script = "\n\n".join(long_sentence * 10 for _ in range(20))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(long_script),
    )

    short_result = service.rewrite(
        source_text="Source text",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="single",
        podcast_length="short",
    )
    long_result = service.rewrite(
        source_text="Source text",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="single",
        podcast_length="long",
    )

    assert len(short_result.split()) <= get_podcast_length_target("short").max_spoken_words + 5
    assert len(long_result.split()) <= get_podcast_length_target("long").max_spoken_words + 5
    assert len(long_result.split()) > len(short_result.split())


def test_rewrite_service_generates_clean_title_from_provider(tmp_path: Path, monkeypatch) -> None:
    service = RewriteService(_build_settings(tmp_path))
    monkeypatch.setattr(
        service,
        "_build_provider",
        lambda: _FakeProvider(
            "Script text.",
            title_response='Title: "Quantum Mechanics, Clearly"',
        ),
    )

    result = service.generate_title(
        script_text="HOST_A: Welcome back.\nHOST_B: Glad to be here.",
        source_type="webpage",
        script_mode="duo",
    )

    assert result == "Quantum Mechanics, Clearly"
