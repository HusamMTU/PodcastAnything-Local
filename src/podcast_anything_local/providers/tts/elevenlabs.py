"""ElevenLabs-backed TTS provider."""

from __future__ import annotations

import json
import re

import requests

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError
from podcast_anything_local.providers.tts.wav_utils import join_wav_segments, wrap_pcm_as_wav

_PCM_OUTPUT_FORMAT_RE = re.compile(r"^pcm_(\d+)$")

_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "aac": "audio/aac",
    "opus": "audio/ogg",
    "ulaw": "audio/basic",
}


class ElevenLabsTTSProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model_id: str,
        dialogue_model_id: str,
        output_format: str,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._dialogue_model_id = dialogue_model_id
        self._output_format = output_format.strip().lower()

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
                },
                json={"text": text, "model_id": self._model_id},
                timeout=180,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TTSProviderError(
                f"ElevenLabs request failed: {self._response_error_detail(getattr(exc, 'response', None), exc)}"
            ) from exc
        if not response.content:
            raise TTSProviderError("ElevenLabs did not return audio content.")
        if self._is_pcm_output():
            sample_rate = self._pcm_sample_rate()
            return wrap_pcm_as_wav(
                response.content,
                sample_rate=sample_rate,
            )
        return SynthesizedAudio(
            data=response.content,
            file_name=f"audio.{self._file_extension()}",
            content_type=self._content_type(),
        )

    def synthesize_dialogue(
        self,
        *,
        turns: list[tuple[str, str]],
        voice_id_a: str | None,
        voice_id_b: str | None,
    ) -> SynthesizedAudio:
        if not self._api_key:
            raise TTSProviderError("ELEVENLABS_API_KEY is required for elevenlabs TTS.")
        if not voice_id_a or not voice_id_b:
            raise TTSProviderError("Both voice_id_a and voice_id_b are required for elevenlabs dialogue.")
        if not turns:
            raise TTSProviderError("At least one dialogue turn is required for elevenlabs dialogue.")

        inputs = [
            {
                "text": text,
                "voice_id": voice_id_a if speaker == "HOST_A" else voice_id_b,
            }
            for speaker, text in turns
        ]

        try:
            response = requests.post(
                "https://api.elevenlabs.io/v1/text-to-dialogue",
                params={"output_format": self._output_format},
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": inputs,
                    "model_id": self._dialogue_model_id,
                },
                timeout=180,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TTSProviderError(
                f"ElevenLabs dialogue request failed: {self._response_error_detail(getattr(exc, 'response', None), exc)}"
            ) from exc
        if not response.content:
            raise TTSProviderError("ElevenLabs dialogue did not return audio content.")
        if self._is_pcm_output():
            return wrap_pcm_as_wav(
                response.content,
                sample_rate=self._pcm_sample_rate(),
            )
        return SynthesizedAudio(
            data=response.content,
            file_name=f"audio.{self._file_extension()}",
            content_type=self._content_type(),
        )

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        if not segments:
            raise TTSProviderError("No audio segments were provided.")
        if len(segments) == 1:
            return segments[0]
        if self._is_pcm_output():
            return join_wav_segments(segments)
        raise TTSProviderError(
            "ElevenLabs can only join multi-turn audio when ELEVENLABS_OUTPUT_FORMAT uses PCM, for example pcm_44100."
        )

    def _is_pcm_output(self) -> bool:
        return _PCM_OUTPUT_FORMAT_RE.match(self._output_format) is not None

    def _pcm_sample_rate(self) -> int:
        match = _PCM_OUTPUT_FORMAT_RE.match(self._output_format)
        if not match:
            raise TTSProviderError(
                "ELEVENLABS_OUTPUT_FORMAT must look like pcm_<sample_rate> for PCM synthesis."
            )
        return int(match.group(1))

    def _file_extension(self) -> str:
        prefix = self._output_format.split("_", 1)[0]
        if prefix == "mp3":
            return "mp3"
        if prefix == "aac":
            return "aac"
        if prefix == "opus":
            return "opus"
        if prefix == "ulaw":
            return "ulaw"
        return prefix

    def _content_type(self) -> str:
        prefix = self._output_format.split("_", 1)[0]
        return _CONTENT_TYPES.get(prefix, "application/octet-stream")

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
        detail = payload.get("detail")
        if isinstance(detail, dict):
            message = detail.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return json.dumps(payload)
