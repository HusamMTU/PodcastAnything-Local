from __future__ import annotations

import wave
from io import BytesIO

import pytest

from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProviderError
from podcast_anything_local.providers.tts.elevenlabs import ElevenLabsTTSProvider


class _Response:
    def __init__(
        self, *, content: bytes, status_code: int = 200, payload: dict | None = None
    ) -> None:
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


def test_elevenlabs_tts_provider_calls_text_to_speech(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, str],
        timeout: int,
    ):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response(content=b"fake-mp3")

    monkeypatch.setattr("podcast_anything_local.providers.tts.elevenlabs.requests.post", _fake_post)
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    audio = provider.synthesize(text="Hello world.", voice_id="voice-123")

    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice-123"
    assert captured["params"] == {"output_format": "mp3_44100_128"}
    assert captured["headers"] == {
        "xi-api-key": "test-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "text": "Hello world.",
        "model_id": "eleven_multilingual_v2",
    }
    assert captured["timeout"] == 180
    assert audio.file_name == "audio.mp3"
    assert audio.content_type == "audio/mpeg"
    assert audio.data == b"fake-mp3"


def test_elevenlabs_pcm_synthesis_is_wrapped_as_wav(monkeypatch) -> None:
    pcm_data = (1).to_bytes(2, "little", signed=True) * 8

    def _fake_post(
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, str],
        timeout: int,
    ):
        del url, params, headers, json, timeout
        return _Response(content=pcm_data)

    monkeypatch.setattr("podcast_anything_local.providers.tts.elevenlabs.requests.post", _fake_post)
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="pcm_44100",
    )

    audio = provider.synthesize(text="Hello world.", voice_id="voice-123")

    assert audio.file_name == "audio.wav"
    assert audio.content_type == "audio/wav"
    assert audio.data.startswith(b"RIFF")
    with wave.open(BytesIO(audio.data), "rb") as wav_file:
        assert wav_file.getframerate() == 44100
        assert wav_file.getnchannels() == 1


def test_elevenlabs_tts_provider_joins_pcm_backed_wav_segments() -> None:
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="pcm_44100",
    )

    def _wav_bytes(value: int) -> bytes:
        buffer = BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(44100)
            wav_file.writeframes((value.to_bytes(2, "little", signed=True)) * 4)
        return buffer.getvalue()

    joined = provider.join(
        [
            SynthesizedAudio(data=_wav_bytes(1), file_name="audio.wav", content_type="audio/wav"),
            SynthesizedAudio(data=_wav_bytes(2), file_name="audio.wav", content_type="audio/wav"),
        ]
    )

    assert joined.file_name == "audio.wav"
    assert joined.content_type == "audio/wav"
    assert joined.data.startswith(b"RIFF")


def test_elevenlabs_tts_provider_rejects_multi_turn_join_for_non_pcm() -> None:
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    with pytest.raises(TTSProviderError, match="ELEVENLABS_OUTPUT_FORMAT uses PCM"):
        provider.join(
            [
                SynthesizedAudio(data=b"one", file_name="audio.mp3", content_type="audio/mpeg"),
                SynthesizedAudio(data=b"two", file_name="audio.mp3", content_type="audio/mpeg"),
            ]
        )


def test_elevenlabs_tts_provider_surfaces_api_error_message(monkeypatch) -> None:
    def _fake_post(
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, str],
        timeout: int,
    ):
        del url, params, headers, json, timeout
        return _Response(
            content=b"",
            status_code=400,
            payload={"detail": {"message": "voice not found"}},
        )

    monkeypatch.setattr("podcast_anything_local.providers.tts.elevenlabs.requests.post", _fake_post)
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    with pytest.raises(TTSProviderError, match="voice not found"):
        provider.synthesize(text="Hello world.", voice_id="bad-voice")


def test_elevenlabs_dialogue_provider_calls_text_to_dialogue(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, object],
        timeout: int,
    ):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response(content=b"dialogue-mp3")

    monkeypatch.setattr("podcast_anything_local.providers.tts.elevenlabs.requests.post", _fake_post)
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    audio = provider.synthesize_dialogue(
        turns=[("HOST_A", "Welcome back."), ("HOST_B", "Glad to be here.")],
        voice_id_a="voice-a",
        voice_id_b="voice-b",
    )

    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-dialogue"
    assert captured["params"] == {"output_format": "mp3_44100_128"}
    assert captured["headers"] == {
        "xi-api-key": "test-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "inputs": [
            {"text": "Welcome back.", "voice_id": "voice-a"},
            {"text": "Glad to be here.", "voice_id": "voice-b"},
        ],
        "model_id": "eleven_v3",
    }
    assert captured["timeout"] == 180
    assert audio.file_name == "audio.mp3"
    assert audio.content_type == "audio/mpeg"
    assert audio.data == b"dialogue-mp3"


def test_elevenlabs_stream_synthesize_uses_stream_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _StreamingResponse(_Response):
        def iter_content(self, chunk_size: int = 1):
            captured["chunk_size"] = chunk_size
            yield b"chunk-a"
            yield b"chunk-b"

    def _fake_post(
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, str],
        timeout: int,
        stream: bool,
    ):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        captured["stream"] = stream
        return _StreamingResponse(content=b"ignored")

    monkeypatch.setattr("podcast_anything_local.providers.tts.elevenlabs.requests.post", _fake_post)
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="mp3_44100_128",
    )
    streamed_chunks: list[bytes] = []

    audio = provider.stream_synthesize(
        text="Hello world.",
        voice_id="voice-123",
        on_chunk=streamed_chunks.append,
    )

    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice-123/stream"
    assert captured["params"] == {"output_format": "mp3_44100_128"}
    assert captured["stream"] is True
    assert captured["json"] == {
        "text": "Hello world.",
        "model_id": "eleven_multilingual_v2",
    }
    assert streamed_chunks == [b"chunk-a", b"chunk-b"]
    assert audio.data == b"chunk-achunk-b"
    assert audio.file_name == "audio.mp3"


def test_elevenlabs_stream_dialogue_uses_stream_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _StreamingResponse(_Response):
        def iter_content(self, chunk_size: int = 1):
            captured["chunk_size"] = chunk_size
            yield b"dialogue-a"
            yield b"dialogue-b"

    def _fake_post(
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        json: dict[str, object],
        timeout: int,
        stream: bool,
    ):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        captured["stream"] = stream
        return _StreamingResponse(content=b"ignored")

    monkeypatch.setattr("podcast_anything_local.providers.tts.elevenlabs.requests.post", _fake_post)
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        model_id="eleven_multilingual_v2",
        dialogue_model_id="eleven_v3",
        output_format="mp3_44100_128",
    )
    streamed_chunks: list[bytes] = []

    audio = provider.stream_synthesize_dialogue(
        turns=[("HOST_A", "Welcome back."), ("HOST_B", "Glad to be here.")],
        voice_id_a="voice-a",
        voice_id_b="voice-b",
        on_chunk=streamed_chunks.append,
    )

    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-dialogue/stream"
    assert captured["params"] == {"output_format": "mp3_44100_128"}
    assert captured["stream"] is True
    assert captured["json"] == {
        "inputs": [
            {"text": "Welcome back.", "voice_id": "voice-a"},
            {"text": "Glad to be here.", "voice_id": "voice-b"},
        ],
        "model_id": "eleven_v3",
    }
    assert streamed_chunks == [b"dialogue-a", b"dialogue-b"]
    assert audio.data == b"dialogue-adialogue-b"
    assert audio.file_name == "audio.mp3"
