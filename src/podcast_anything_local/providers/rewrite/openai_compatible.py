"""OpenAI-compatible rewrite provider."""

from __future__ import annotations

import base64
import json
import time

import requests

from podcast_anything_local.providers.rewrite.base import RewriteProviderError
from podcast_anything_local.providers.rewrite.prompting import (
    build_document_map_prompt,
    build_pdf_chunk_summary_prompt,
    build_podcast_plan_prompt,
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
        podcast_length: str = "medium",
    ) -> str:
        prompt = build_podcast_prompt(
            source_text,
            title=title,
            style=style,
            source_type=source_type,
            script_mode=script_mode,
            podcast_length=podcast_length,
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

    def summarize_pdf_chunk(
        self,
        *,
        pdf_bytes: bytes,
        filename: str,
        title: str | None,
        chunk_index: int,
        chunk_count: int,
        page_start: int,
        page_end: int,
        script_mode: str,
        supplemental_text: str | None = None,
    ) -> dict[str, object]:
        prompt = build_pdf_chunk_summary_prompt(
            title=title,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
            page_start=page_start,
            page_end=page_end,
            script_mode=script_mode,
            supplemental_text=supplemental_text,
        )
        return self._complete_json_response(
            prompt=prompt,
            schema_name="pdf_chunk_summary",
            schema=_pdf_chunk_summary_schema(),
            pdf_bytes=pdf_bytes,
            filename=filename,
            empty_error="OpenAI-compatible response did not include a PDF chunk summary.",
        )

    def build_document_map(
        self,
        *,
        chunk_summaries: list[dict[str, object]],
        title: str | None,
        script_mode: str,
    ) -> dict[str, object]:
        prompt = build_document_map_prompt(
            chunk_summaries=chunk_summaries,
            title=title,
            script_mode=script_mode,
        )
        return self._complete_json_response(
            prompt=prompt,
            schema_name="document_map",
            schema=_document_map_schema(),
            empty_error="OpenAI-compatible response did not include a document map.",
        )

    def build_podcast_plan(
        self,
        *,
        document_map: dict[str, object],
        title: str | None,
        script_mode: str,
        podcast_length: str = "medium",
    ) -> dict[str, object]:
        prompt = build_podcast_plan_prompt(
            document_map=document_map,
            title=title,
            script_mode=script_mode,
            podcast_length=podcast_length,
        )
        return self._complete_json_response(
            prompt=prompt,
            schema_name="podcast_plan",
            schema=_podcast_plan_schema(),
            empty_error="OpenAI-compatible response did not include a podcast plan.",
        )

    def _complete(self, *, prompt: str, empty_error: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        response = self._post_json(
            endpoint="/chat/completions",
            headers=headers,
            payload={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
            },
        )
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

    def _complete_json_response(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: dict[str, object],
        empty_error: str,
        pdf_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        content: list[dict[str, object]] = [{"type": "input_text", "text": prompt}]
        if pdf_bytes is not None:
            content.append(
                {
                    "type": "input_file",
                    "filename": filename or "document.pdf",
                    "file_data": (
                        "data:application/pdf;base64,"
                        f"{base64.b64encode(pdf_bytes).decode('ascii')}"
                    ),
                }
            )

        response = self._post_json(
            endpoint="/responses",
            headers=headers,
            payload={
                "model": self._model,
                "input": [{"role": "user", "content": content}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
                "temperature": 0.2,
            },
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            _, error_message = _extract_openai_error(response)
            detail = error_message or str(exc)
            raise RewriteProviderError(f"OpenAI-compatible request failed: {detail}") from exc

        payload = response.json()
        text = _extract_responses_output_text(payload)
        if not text:
            raise RewriteProviderError(empty_error)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RewriteProviderError(
                f"OpenAI-compatible response did not contain valid JSON. Details: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise RewriteProviderError("OpenAI-compatible response JSON must be an object.")
        return parsed

    def _post_json(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> requests.Response:
        response = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = requests.post(
                    f"{self._base_url}{endpoint}",
                    headers=headers,
                    json=payload,
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
        return response


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


def _extract_responses_output_text(payload: dict[str, object]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        return ""

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _pdf_chunk_summary_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_start": {"type": "integer"},
            "page_end": {"type": "integer"},
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "visual_elements": {"type": "array", "items": {"type": "string"}},
            "podcast_angles": {"type": "array", "items": {"type": "string"}},
            "must_include_details": {"type": "array", "items": {"type": "string"}},
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "page_start",
            "page_end",
            "summary",
            "key_points",
            "visual_elements",
            "podcast_angles",
            "must_include_details",
            "caveats",
        ],
    }


def _document_map_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overall_summary": {"type": "string"},
            "narrative_arc": {"type": "array", "items": {"type": "string"}},
            "must_include": {"type": "array", "items": {"type": "string"}},
            "supporting_details": {"type": "array", "items": {"type": "string"}},
            "visual_takeaways": {"type": "array", "items": {"type": "string"}},
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "overall_summary",
            "narrative_arc",
            "must_include",
            "supporting_details",
            "visual_takeaways",
            "caveats",
        ],
    }


def _podcast_plan_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "working_title": {"type": "string"},
            "audience": {"type": "string"},
            "angle": {"type": "string"},
            "intro": {"type": "string"},
            "outro": {"type": "string"},
            "must_include": {"type": "array", "items": {"type": "string"}},
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "purpose": {"type": "string"},
                        "beats": {"type": "array", "items": {"type": "string"}},
                        "source_pages": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["name", "purpose", "beats", "source_pages"],
                },
            },
        },
        "required": [
            "working_title",
            "audience",
            "angle",
            "intro",
            "outro",
            "must_include",
            "segments",
        ],
    }
