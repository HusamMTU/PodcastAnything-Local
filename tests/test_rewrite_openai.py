from __future__ import annotations

import requests

from podcast_anything_local.providers.rewrite.base import RewriteProviderError
from podcast_anything_local.providers.rewrite.openai_compatible import OpenAICompatibleRewriteProvider


class _Response:
    def __init__(
        self,
        payload: dict,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}", response=self)

    def json(self) -> dict:
        return self._payload


def test_openai_rewrite_retries_transient_429(monkeypatch) -> None:
    responses = [
        _Response(
            {"error": {"type": "rate_limit_exceeded", "message": "Rate limit exceeded"}},
            status_code=429,
            headers={"Retry-After": "0"},
        ),
        _Response(
            {"choices": [{"message": {"content": "Generated script."}}]},
            status_code=200,
        ),
    ]
    calls: list[int] = []

    def fake_post(url, headers=None, json=None, timeout=0):
        calls.append(timeout)
        return responses.pop(0)

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    provider = OpenAICompatibleRewriteProvider(
        base_url="https://api.openai.com/v1",
        api_key="key",
        model="gpt-4o-mini",
    )
    result = provider.rewrite(
        source_text="Source text.",
        title="Title",
        style="podcast",
        source_type="text",
        script_mode="single",
    )

    assert result == "Generated script."
    assert len(calls) == 2


def test_openai_rewrite_surfaces_quota_429_cleanly(monkeypatch) -> None:
    def fake_post(url, headers=None, json=None, timeout=0):
        return _Response(
            {
                "error": {
                    "type": "insufficient_quota",
                    "message": "You exceeded your current quota, please check your plan and billing details.",
                }
            },
            status_code=429,
        )

    monkeypatch.setattr("requests.post", fake_post)

    provider = OpenAICompatibleRewriteProvider(
        base_url="https://api.openai.com/v1",
        api_key="key",
        model="gpt-4o-mini",
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
        assert "out of quota" in message
        assert "billing" in message.lower()
    else:
        raise AssertionError("Expected RewriteProviderError")


def test_openai_rewrite_surfaces_non_429_error_message(monkeypatch) -> None:
    def fake_post(url, headers=None, json=None, timeout=0):
        return _Response(
            {"error": {"type": "invalid_request_error", "message": "Bad request payload."}},
            status_code=400,
        )

    monkeypatch.setattr("requests.post", fake_post)

    provider = OpenAICompatibleRewriteProvider(
        base_url="https://api.openai.com/v1",
        api_key="key",
        model="gpt-4o-mini",
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
        assert "Bad request payload." in str(exc)
    else:
        raise AssertionError("Expected RewriteProviderError")


def test_openai_generate_title_cleans_plain_text_title(monkeypatch) -> None:
    def fake_post(url, headers=None, json=None, timeout=0):
        return _Response(
            {"choices": [{"message": {"content": 'Title: "Quantum Mechanics, Clearly"'}}]},
            status_code=200,
        )

    monkeypatch.setattr("requests.post", fake_post)

    provider = OpenAICompatibleRewriteProvider(
        base_url="https://api.openai.com/v1",
        api_key="key",
        model="gpt-4o-mini",
    )

    result = provider.generate_title(
        script_text="Welcome back. Today we're talking quantum mechanics.",
        source_type="webpage",
        script_mode="single",
    )

    assert result == "Quantum Mechanics, Clearly"
