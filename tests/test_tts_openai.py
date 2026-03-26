from __future__ import annotations

import io
import wave

import pytest

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError
from podcast_anything_local.providers.tts.openai import OpenAITTSProvider


class _Response:
    def __init__(self, *, content: bytes, status_code: int = 200, payload: dict | None = None) -> None:
        self.content = content
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError("bad request", response=self)

    def json(self) -> dict:
        return self._payload

    def iter_content(self, chunk_size: int = 1):
        del chunk_size
        yield self.content


def _wav_bytes(value: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes((value.to_bytes(2, "little", signed=True)) * 4)
    return buffer.getvalue()


def test_openai_tts_provider_calls_audio_speech(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, *, headers: dict[str, str], json: dict[str, str], timeout: int):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response(content=_wav_bytes(1))

    monkeypatch.setattr("podcast_anything_local.providers.tts.openai.requests.post", _fake_post)
    provider = OpenAITTSProvider(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini-tts",
        response_format="wav",
    )

    audio = provider.synthesize(text="Hello world.", voice_id="marin")

    assert captured["url"] == "https://api.openai.com/v1/audio/speech"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "input": "Hello world.",
        "response_format": "wav",
    }
    assert captured["timeout"] == 180
    assert audio.file_name == "audio.wav"
    assert audio.content_type == "audio/wav"
    assert audio.data.startswith(b"RIFF")


def test_openai_tts_provider_joins_wav_segments() -> None:
    provider = OpenAITTSProvider(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini-tts",
        response_format="wav",
    )

    joined = provider.join(
        [
            SynthesizedAudio(data=_wav_bytes(1), file_name="audio.wav", content_type="audio/wav"),
            SynthesizedAudio(data=_wav_bytes(2), file_name="audio.wav", content_type="audio/wav"),
        ]
    )

    assert joined.file_name == "audio.wav"
    assert joined.content_type == "audio/wav"
    assert joined.data.startswith(b"RIFF")


def test_openai_tts_provider_rejects_join_for_non_wav_multi_turn_audio() -> None:
    provider = OpenAITTSProvider(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini-tts",
        response_format="mp3",
    )

    with pytest.raises(TTSProviderError, match="OPENAI_TTS_RESPONSE_FORMAT=wav"):
        provider.join(
            [
                SynthesizedAudio(data=b"one", file_name="audio.mp3", content_type="audio/mpeg"),
                SynthesizedAudio(data=b"two", file_name="audio.mp3", content_type="audio/mpeg"),
            ]
        )


def test_openai_tts_provider_surfaces_api_error_message(monkeypatch) -> None:
    def _fake_post(url: str, *, headers: dict[str, str], json: dict[str, str], timeout: int):
        del url, headers, json, timeout
        return _Response(
            content=b"",
            status_code=400,
            payload={"error": {"message": "voice not supported"}},
        )

    monkeypatch.setattr("podcast_anything_local.providers.tts.openai.requests.post", _fake_post)
    provider = OpenAITTSProvider(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini-tts",
        response_format="wav",
    )

    with pytest.raises(TTSProviderError, match="voice not supported"):
        provider.synthesize(text="Hello world.", voice_id="bad-voice")


def test_openai_tts_provider_streams_audio_speech(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _StreamingResponse(_Response):
        def iter_content(self, chunk_size: int = 1):
            captured["chunk_size"] = chunk_size
            yield b"chunk-a"
            yield b"chunk-b"

    def _fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, str],
        timeout: int,
        stream: bool,
    ):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        captured["stream"] = stream
        return _StreamingResponse(content=b"ignored")

    monkeypatch.setattr("podcast_anything_local.providers.tts.openai.requests.post", _fake_post)
    provider = OpenAITTSProvider(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini-tts",
        response_format="wav",
    )
    chunks: list[bytes] = []

    audio = provider.stream_synthesize(
        text="Hello world.",
        voice_id="marin",
        on_chunk=chunks.append,
    )

    assert captured["url"] == "https://api.openai.com/v1/audio/speech"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "input": "Hello world.",
        "response_format": "wav",
    }
    assert captured["timeout"] == 180
    assert captured["stream"] is True
    assert chunks == [b"chunk-a", b"chunk-b"]
    assert audio.data == b"chunk-achunk-b"
    assert audio.file_name == "audio.wav"
    assert audio.content_type == "audio/wav"
