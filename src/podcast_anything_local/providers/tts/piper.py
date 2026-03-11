"""Piper-backed local text-to-speech provider."""

from __future__ import annotations

import io
import wave
from pathlib import Path

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError
from podcast_anything_local.providers.tts.wav_utils import join_wav_segments

try:
    from piper.config import SynthesisConfig
    from piper.voice import PiperVoice
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    PiperVoice = None
    SynthesisConfig = None


class PiperTTSProvider:
    """Use the `piper-tts` Python package for local synthesis."""

    _voice_cache: dict[tuple[str, str | None], object] = {}

    def __init__(
        self,
        *,
        model_path: str | None,
        model_path_b: str | None,
        config_path: str | None,
        config_path_b: str | None,
        speaker_id: str | None,
        speaker_id_b: str | None,
    ) -> None:
        self._model_path = model_path
        self._model_path_b = model_path_b
        self._config_path = config_path
        self._config_path_b = config_path_b
        self._speaker_id = speaker_id
        self._speaker_id_b = speaker_id_b

    def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
    ) -> SynthesizedAudio:
        cleaned = text.strip()
        if not cleaned:
            raise TTSProviderError("Input text is empty.")

        model_path, config_path, speaker_id = self._resolve_voice_inputs(
            voice_id=voice_id,
            speaker=speaker,
        )
        if not model_path:
            raise TTSProviderError(
                "PIPER_MODEL_PATH is required for the piper provider. "
                "Set it in the environment or pass a model path via voice_id."
            )
        if PiperVoice is None or SynthesisConfig is None:
            raise TTSProviderError(
                "The `piper-tts` package is not installed. Install the project with the "
                "`piper` extra to use the piper provider."
            )
        return self._synthesize_with_package(
            text=cleaned,
            model_path=model_path,
            config_path=config_path,
            speaker_id=speaker_id,
        )

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        return join_wav_segments(segments, file_name="audio.wav")

    def _synthesize_with_package(
        self,
        *,
        text: str,
        model_path: str,
        config_path: str | None,
        speaker_id: str | None,
    ) -> SynthesizedAudio:
        voice = self._load_voice(model_path=model_path, config_path=config_path)
        resolved_speaker_id = self._resolve_speaker_id(voice=voice, speaker_id=speaker_id)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            voice.synthesize_wav(
                text,
                wav_file,
                syn_config=SynthesisConfig(speaker_id=resolved_speaker_id),
            )

        return SynthesizedAudio(
            data=buffer.getvalue(),
            file_name="audio.wav",
            content_type="audio/wav",
        )

    def _load_voice(self, *, model_path: str, config_path: str | None):
        cache_key = (str(Path(model_path).resolve()), str(Path(config_path).resolve()) if config_path else None)
        voice = self._voice_cache.get(cache_key)
        if voice is not None:
            return voice
        assert PiperVoice is not None
        voice = PiperVoice.load(model_path=model_path, config_path=config_path)
        self._voice_cache[cache_key] = voice
        return voice

    def _resolve_speaker_id(self, *, voice, speaker_id: str | None) -> int | None:
        if not speaker_id:
            return None
        cleaned = speaker_id.strip()
        if not cleaned:
            return None
        if cleaned.isdigit():
            return int(cleaned)
        speaker_map = getattr(voice.config, "speaker_id_map", {}) or {}
        if cleaned in speaker_map:
            return int(speaker_map[cleaned])
        raise TTSProviderError(
            f"Unknown Piper speaker identifier '{speaker_id}'. Use a numeric speaker id "
            "or a key from the model's speaker_id_map."
        )

    def _resolve_voice_inputs(
        self,
        *,
        voice_id: str | None,
        speaker: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        use_b = speaker == "host_b"
        model_path = self._model_path_b if use_b and self._model_path_b else self._model_path
        config_path = self._config_path_b if use_b and self._config_path_b else self._config_path
        speaker_id = self._speaker_id_b if use_b and self._speaker_id_b else self._speaker_id

        cleaned_voice = (voice_id or "").strip()
        if cleaned_voice:
            candidate_path = Path(cleaned_voice).expanduser()
            if candidate_path.exists():
                model_path = str(candidate_path.resolve())
            else:
                speaker_id = cleaned_voice

        return model_path, config_path, speaker_id
