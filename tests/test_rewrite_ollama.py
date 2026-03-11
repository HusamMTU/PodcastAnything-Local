from __future__ import annotations

import requests

from podcast_anything_local.providers.rewrite.base import RewriteProviderError
from podcast_anything_local.providers.rewrite.ollama import OllamaRewriteProvider


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self) -> dict:
        return self._payload


class _StreamingResponse:
    def __init__(self, chunks: list[str], status_code: int = 200) -> None:
        self._chunks = chunks
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def iter_lines(self, decode_unicode: bool = False):
        for chunk in self._chunks:
            yield chunk


def test_list_models_reads_names(monkeypatch) -> None:
    def fake_get(url, timeout):
        assert url == "http://localhost:11434/api/tags"
        return _Response({"models": [{"name": "qwen3"}, {"model": "gemma3"}]})

    monkeypatch.setattr("requests.get", fake_get)

    provider = OllamaRewriteProvider(base_url="http://localhost:11434/api", model="qwen3")

    assert provider.list_models() == ["qwen3", "gemma3"]


def test_ensure_model_available_errors_when_missing(monkeypatch) -> None:
    def fake_get(url, timeout):
        return _Response({"models": [{"name": "gemma3"}]})

    monkeypatch.setattr("requests.get", fake_get)

    provider = OllamaRewriteProvider(base_url="http://localhost:11434/api", model="qwen3")

    try:
        provider.ensure_model_available()
    except RewriteProviderError as exc:
        assert "ollama pull qwen3" in str(exc)
    else:
        raise AssertionError("Expected RewriteProviderError")


def test_rewrite_calls_generate_after_model_check(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get(url, timeout):
        calls.append(("GET", url))
        return _Response({"models": [{"name": "qwen3"}]})

    def fake_post(url, json=None, timeout=0):
        calls.append(("POST", url))
        assert json["model"] == "qwen3"
        assert json["stream"] is False
        assert timeout == 600
        return _Response({"response": "Generated script."})

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("requests.post", fake_post)

    provider = OllamaRewriteProvider(base_url="http://localhost:11434/api", model="qwen3")
    result = provider.rewrite(
        source_text="Source text.",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="single",
    )

    assert result == "Generated script."
    assert calls == [
        ("GET", "http://localhost:11434/api/tags"),
        ("POST", "http://localhost:11434/api/generate"),
    ]


def test_generate_title_calls_generate_after_model_check(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get(url, timeout):
        calls.append(("GET", url))
        return _Response({"models": [{"name": "qwen3"}]})

    def fake_post(url, json=None, timeout=0):
        calls.append(("POST", url))
        assert json["model"] == "qwen3"
        assert json["stream"] is False
        return _Response({"response": 'Title: "Quantum Mechanics, Clearly"'})

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("requests.post", fake_post)

    provider = OllamaRewriteProvider(base_url="http://localhost:11434/api", model="qwen3")
    result = provider.generate_title(
        script_text="HOST_A: Welcome back.\nHOST_B: Let's talk quantum mechanics.",
        source_type="webpage",
        script_mode="duo",
    )

    assert result == "Quantum Mechanics, Clearly"
    assert calls == [
        ("GET", "http://localhost:11434/api/tags"),
        ("POST", "http://localhost:11434/api/generate"),
    ]


def test_rewrite_surfaces_timeout_with_actionable_message(monkeypatch) -> None:
    def fake_get(url, timeout):
        return _Response({"models": [{"name": "qwen3"}]})

    def fake_post(url, json=None, timeout=0):
        raise requests.ReadTimeout("read timeout")

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("requests.post", fake_post)

    provider = OllamaRewriteProvider(
        base_url="http://localhost:11434/api",
        model="qwen3",
        generate_timeout_seconds=900,
    )

    try:
        provider.rewrite(
            source_text="Source text.",
            title="Title",
            style="podcast",
            source_type="text",
            script_mode="single",
        )
    except RewriteProviderError as exc:
        message = str(exc)
        assert "900 seconds" in message
        assert "OLLAMA_GENERATE_TIMEOUT_SECONDS" in message
        assert "smaller model" in message
    else:
        raise AssertionError("Expected RewriteProviderError")


def test_stream_rewrite_yields_chunked_response(monkeypatch) -> None:
    def fake_get(url, timeout):
        return _Response({"models": [{"name": "qwen3"}]})

    def fake_post(url, json=None, timeout=0, stream=False):
        assert stream is True
        assert json["stream"] is True
        return _StreamingResponse(
            [
                '{"response":"Hello ","done":false}',
                '{"response":"world.","done":false}',
                '{"response":"","done":true}',
            ]
        )

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("requests.post", fake_post)

    provider = OllamaRewriteProvider(base_url="http://localhost:11434/api", model="qwen3")
    chunks: list[str] = []
    result = provider.stream_rewrite(
        source_text="Source text.",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="single",
        on_chunk=chunks.append,
    )

    assert chunks == ["Hello ", "world."]
    assert result == "Hello world."
