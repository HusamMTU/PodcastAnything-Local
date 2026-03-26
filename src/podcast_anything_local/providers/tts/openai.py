"""OpenAI-backed text-to-speech provider."""

from __future__ import annotations

from collections.abc import Callable
import json

import requests

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError
from podcast_anything_local.providers.tts.wav_utils import join_wav_segments

_CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "opus": "audio/opus",
    "pcm": "audio/L16",
}


class OpenAITTSProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        response_format: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._response_format = response_format.lower().strip()

    def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
    ) -> SynthesizedAudio:
        del speaker
        if not self._api_key:
            raise TTSProviderError("OPENAI_API_KEY is required for openai TTS.")
        if not voice_id:
            raise TTSProviderError("voice_id is required for openai TTS.")
        try:
            response = requests.post(
                f"{self._base_url}/audio/speech",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "voice": voice_id,
                    "input": text,
                    "response_format": self._response_format,
                },
                timeout=180,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TTSProviderError(
                f"OpenAI TTS request failed: {self._response_error_detail(getattr(exc, 'response', None), exc)}"
            ) from exc
        if not response.content:
            raise TTSProviderError("OpenAI TTS did not return audio content.")
        return SynthesizedAudio(
            data=response.content,
            file_name=f"audio.{self._response_format}",
            content_type=_CONTENT_TYPES.get(self._response_format, "application/octet-stream"),
        )

    def stream_synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
        on_chunk: Callable[[bytes], None],
    ) -> SynthesizedAudio:
        del speaker
        if not self._api_key:
            raise TTSProviderError("OPENAI_API_KEY is required for openai TTS.")
        if not voice_id:
            raise TTSProviderError("voice_id is required for openai TTS.")
        try:
            response = requests.post(
                f"{self._base_url}/audio/speech",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "voice": voice_id,
                    "input": text,
                    "response_format": self._response_format,
                },
                timeout=180,
                stream=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TTSProviderError(
                f"OpenAI TTS request failed: {self._response_error_detail(getattr(exc, 'response', None), exc)}"
            ) from exc

        chunks: list[bytes] = []
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue
            chunks.append(chunk)
            on_chunk(chunk)

        content = b"".join(chunks)
        if not content:
            raise TTSProviderError("OpenAI TTS did not return audio content.")
        return SynthesizedAudio(
            data=content,
            file_name=self.live_stream_file_name(),
            content_type=self.live_stream_content_type(),
        )

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        if not segments:
            raise TTSProviderError("No audio segments were provided.")
        if len(segments) == 1:
            return segments[0]
        if self._response_format != "wav":
            raise TTSProviderError(
                "OpenAI TTS can only join multi-turn audio when OPENAI_TTS_RESPONSE_FORMAT=wav."
            )
        return join_wav_segments(segments)

    def supports_live_streaming(self) -> bool:
        return self._response_format != "pcm"

    def live_stream_file_name(self) -> str:
        return f"audio.{self._response_format}"

    def live_stream_content_type(self) -> str:
        return _CONTENT_TYPES.get(self._response_format, "application/octet-stream")

    @staticmethod
    def _response_error_detail(response: requests.Response | None, exc: Exception) -> str:
        if response is None:
            return str(exc)
        try:
            payload = response.json()
        except ValueError:
            return str(exc)
        if not isinstance(payload, dict):
            return str(exc)
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        return json.dumps(payload)
