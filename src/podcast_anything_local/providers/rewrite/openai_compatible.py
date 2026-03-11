"""OpenAI-compatible rewrite provider."""

from __future__ import annotations

import time

import requests

from podcast_anything_local.providers.rewrite.base import RewriteProviderError
from podcast_anything_local.providers.rewrite.prompting import (
    build_podcast_prompt,
    build_title_prompt,
    clean_generated_title,
)

_REQUEST_TIMEOUT_SECONDS = 180
_MAX_RATE_LIMIT_RETRIES = 2


class OpenAICompatibleRewriteProvider:
    def __init__(self, *, base_url: str, api_key: str | None, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def rewrite(
        self,
        *,
        source_text: str,
        title: str | None = None,
        style: str = "podcast",
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        prompt = build_podcast_prompt(
            source_text,
            title=title,
            style=style,
            source_type=source_type,
            script_mode=script_mode,
        )
        return self._complete(
            prompt=prompt,
            empty_error="OpenAI-compatible response did not include script text.",
        )

    def generate_title(
        self,
        *,
        script_text: str,
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        prompt = build_title_prompt(
            script_text,
            source_type=source_type,
            script_mode=script_mode,
        )
        generated = self._complete(
            prompt=prompt,
            empty_error="OpenAI-compatible response did not include a title.",
        )
        return clean_generated_title(generated)

    def _complete(self, *, prompt: str, empty_error: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        response = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = requests.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.5,
                    },
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise RewriteProviderError(f"OpenAI-compatible request failed: {exc}") from exc

            if response.status_code != 429:
                break

            error_type, error_message = _extract_openai_error(response)
            if _is_quota_error(error_type, error_message):
                raise RewriteProviderError(
                    "OpenAI-compatible request failed because the account appears to be out of "
                    f"quota or billing credit. Details: {error_message or '429 Too Many Requests'}"
                )

            if attempt >= _MAX_RATE_LIMIT_RETRIES:
                raise RewriteProviderError(
                    "OpenAI-compatible request hit the provider rate limit and exhausted the "
                    f"automatic retries. Details: {error_message or '429 Too Many Requests'}"
                )

            time.sleep(_retry_delay_seconds(response, attempt))

        assert response is not None
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            _, error_message = _extract_openai_error(response)
            detail = error_message or str(exc)
            raise RewriteProviderError(f"OpenAI-compatible request failed: {detail}") from exc

        payload = response.json()
        choices = payload.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        text = (message.get("content") or "").strip()
        if not text:
            raise RewriteProviderError(empty_error)
        return text


def _extract_openai_error(response: requests.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None, None
    error_type = error.get("type")
    error_message = error.get("message")
    return (
        error_type.strip() if isinstance(error_type, str) and error_type.strip() else None,
        error_message.strip() if isinstance(error_message, str) and error_message.strip() else None,
    )


def _is_quota_error(error_type: str | None, error_message: str | None) -> bool:
    if error_type == "insufficient_quota":
        return True
    lowered = (error_message or "").lower()
    return "quota" in lowered or "billing" in lowered or "credit" in lowered


def _retry_delay_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if isinstance(retry_after, str):
        try:
            value = float(retry_after.strip())
        except ValueError:
            value = 0.0
        if value > 0:
            return min(value, 10.0)
    return float(min(2 ** attempt, 4))
