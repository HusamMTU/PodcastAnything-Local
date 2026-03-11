"""Development TTS provider that emits a synthetic WAV tone."""

from __future__ import annotations

import io
import math
import wave

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError
from podcast_anything_local.providers.tts.wav_utils import join_wav_segments


class WaveTTSProvider:
    """Generate a valid WAV file without any external runtime dependency."""

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
        frequency = 220 if voice_id == "host_b" or speaker == "host_b" else 180
        duration_sec = max(1.0, min(12.0, len(cleaned) / 80.0))
        sample_rate = 22050
        frame_count = int(sample_rate * duration_sec)
        amplitude = 12000
        frames = bytearray()
        for index in range(frame_count):
            sample = int(amplitude * math.sin((2 * math.pi * frequency * index) / sample_rate))
            frames.extend(sample.to_bytes(2, byteorder="little", signed=True))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(frames))

        return SynthesizedAudio(
            data=buffer.getvalue(),
            file_name="audio.wav",
            content_type="audio/wav",
        )

    def join(self, segments: list[SynthesizedAudio]) -> SynthesizedAudio:
        return join_wav_segments(segments, file_name="audio.wav")
