"""Helpers for building and joining WAV audio."""

from __future__ import annotations

import io
import wave

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError


def join_wav_segments(
    segments: list[SynthesizedAudio],
    *,
    file_name: str = "audio.wav",
) -> SynthesizedAudio:
    if not segments:
        raise TTSProviderError("No audio segments were provided.")

    raw_frames = bytearray()
    channels: int | None = None
    sample_width: int | None = None
    sample_rate: int | None = None

    for segment in segments:
        with wave.open(io.BytesIO(segment.data), "rb") as wav_file:
            current_channels = wav_file.getnchannels()
            current_sample_width = wav_file.getsampwidth()
            current_sample_rate = wav_file.getframerate()

            if channels is None:
                channels = current_channels
                sample_width = current_sample_width
                sample_rate = current_sample_rate
            elif (
                current_channels != channels
                or current_sample_width != sample_width
                or current_sample_rate != sample_rate
            ):
                raise TTSProviderError("WAV segments do not share the same audio parameters.")

            raw_frames.extend(wav_file.readframes(wav_file.getnframes()))

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels or 1)
        wav_file.setsampwidth(sample_width or 2)
        wav_file.setframerate(sample_rate or 22050)
        wav_file.writeframes(bytes(raw_frames))

    return SynthesizedAudio(
        data=output.getvalue(),
        file_name=file_name,
        content_type="audio/wav",
    )
