from __future__ import annotations

import io
import wave
from pathlib import Path

from podcast_anything_local.providers.tts.piper import PiperTTSProvider
from podcast_anything_local.providers.tts.wave import WaveTTSProvider


def test_piper_provider_uses_host_b_model_and_voice_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_a = tmp_path / "voice_a.onnx"
    model_b = tmp_path / "voice_b.onnx"
    model_a.write_text("", encoding="utf-8")
    model_b.write_text("", encoding="utf-8")

    observed_calls: list[tuple[str, str | None, int | None]] = []

    class FakeVoice:
        class config:
            speaker_id_map = {"speaker_a": 0, "speaker_b": 1}

        def synthesize_wav(self, text, wav_file, syn_config=None):
            observed_calls.append((text, str(model_b), getattr(syn_config, "speaker_id", None)))
            wav_bytes = WaveTTSProvider().synthesize(text=text, speaker="host_b").data
            with wave.open(io.BytesIO(wav_bytes), "rb") as source_wav:
                wav_file.setframerate(source_wav.getframerate())
                wav_file.setsampwidth(source_wav.getsampwidth())
                wav_file.setnchannels(source_wav.getnchannels())
                wav_file.writeframes(source_wav.readframes(source_wav.getnframes()))

    monkeypatch.setattr(
        PiperTTSProvider,
        "_load_voice",
        lambda self, model_path=None, config_path=None: FakeVoice(),
    )

    provider = PiperTTSProvider(
        model_path=str(model_a),
        model_path_b=str(model_b),
        config_path=None,
        config_path_b=None,
        speaker_id="0",
        speaker_id_b="1",
    )

    result = provider.synthesize(
        text="Hello from Piper.",
        voice_id="3",
        speaker="host_b",
    )

    assert result.content_type == "audio/wav"
    assert observed_calls
    text, used_model, used_speaker = observed_calls[0]
    assert text == "Hello from Piper."
    assert used_model == str(model_b)
    assert used_speaker == 3


def test_piper_join_returns_valid_wav(tmp_path: Path) -> None:
    provider = PiperTTSProvider(
        model_path=str(tmp_path / "voice_a.onnx"),
        model_path_b=None,
        config_path=None,
        config_path_b=None,
        speaker_id=None,
        speaker_id_b=None,
    )
    segment_a = WaveTTSProvider().synthesize(text="First segment.", speaker="host_a")
    segment_b = WaveTTSProvider().synthesize(text="Second segment.", speaker="host_b")

    joined = provider.join([segment_a, segment_b])

    assert joined.file_name == "audio.wav"
    assert joined.content_type == "audio/wav"
    assert len(joined.data) > len(segment_a.data)


def test_piper_provider_uses_sibling_config_for_model_path_override(tmp_path: Path) -> None:
    model_a = tmp_path / "voice_a.onnx"
    config_a = tmp_path / "voice_a.onnx.json"
    model_override = tmp_path / "voice_override.onnx"
    config_override = tmp_path / "voice_override.onnx.json"
    model_a.write_text("", encoding="utf-8")
    config_a.write_text("{}", encoding="utf-8")
    model_override.write_text("", encoding="utf-8")
    config_override.write_text("{}", encoding="utf-8")

    provider = PiperTTSProvider(
        model_path=str(model_a),
        model_path_b=None,
        config_path=str(config_a),
        config_path_b=None,
        speaker_id=None,
        speaker_id_b=None,
    )

    model_path, config_path, speaker_id = provider._resolve_voice_inputs(
        voice_id=str(model_override),
        speaker="host_a",
    )

    assert model_path == str(model_override.resolve())
    assert config_path == str(config_override.resolve())
    assert speaker_id is None
