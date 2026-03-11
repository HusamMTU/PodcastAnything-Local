"""ElevenLabs-backed TTS provider."""

from __future__ import annotations

import requests

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError


class ElevenLabsTTSProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model_id: str,
        output_format: str,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._output_format = output_format

    def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
    ) -> SynthesizedAudio:
        if not self._api_key:
            raise TTSProviderError("ELEVENLABS_API_KEY is required for elevenlabs TTS.")
        if not voice_id:
            raise TTSProviderError("voice_id is required for elevenlabs TTS.")
        try:
            response = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                params={"output_format": self._output_format},
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={"text": text, "model_id": self._model_id},
                timeout=180,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TTSProviderError(f"ElevenLabs request failed: {exc}") from exc
        if not response.content:
            raise TTSProviderError("ElevenLabs did not return audio content.")
        return SynthesizedAudio(
            data=response.content,
            file_name="audio.mp3",
            content_type="audio/mpeg",
        )

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        if not segments:
            raise TTSProviderError("No audio segments were provided.")
        return SynthesizedAudio(
            data=b"".join(segment.data for segment in segments),
            file_name="audio.mp3",
            content_type="audio/mpeg",
        )
