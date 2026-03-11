"""TTS provider interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TTSProviderError(RuntimeError):
    """Raised when text-to-speech synthesis fails."""


@dataclass(frozen=True, slots=True)
class SynthesizedAudio:
    data: bytes
    file_name: str
    content_type: str


class TTSProvider(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        speaker: str | None = None,
    ) -> SynthesizedAudio:
        """Synthesize one chunk of audio."""

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        """Join synthesized segments into one artifact."""
