"""Ollama-backed rewrite provider."""

from __future__ import annotations

import json
from collections.abc import Callable

import requests

from podcast_anything_local.providers.rewrite.base import RewriteProviderError
from podcast_anything_local.providers.rewrite.prompting import (
    build_podcast_prompt,
    build_title_prompt,
    clean_generated_title,
)


class OllamaRewriteProvider:
    def __init__(self, *, base_url: str, model: str, generate_timeout_seconds: int = 600) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._generate_timeout_seconds = generate_timeout_seconds

    def list_models(self) -> list[str]:
        payload = self._request_json(
            "GET",
            "/tags",
            timeout=15,
            operation="list local models",
        )
        models: list[str] = []
        for item in payload.get("models", []):
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if isinstance(name, str) and name.strip():
                models.append(name.strip())
        return models

    def ensure_model_available(self, *, pull_if_missing: bool = False) -> None:
        available_models = self.list_models()
        if self._model in available_models:
            return

        if pull_if_missing:
            self.pull_model()
            available_models = self.list_models()
            if self._model in available_models:
                return

        raise RewriteProviderError(
            f"Ollama model '{self._model}' is not available locally. "
            f"Pull it first with `ollama pull {self._model}` or run "
            f"`make pull-ollama-model MODEL={self._model}`."
        )

    def pull_model(self) -> None:
        self._request_json(
            "POST",
            "/pull",
            json={"model": self._model, "stream": False},
            timeout=900,
            operation=f"pull model '{self._model}'",
        )

    def rewrite(
        self,
        *,
        source_text: str,
        title: str | None = None,
        style: str = "podcast",
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        self.ensure_model_available()
        prompt = build_podcast_prompt(
            source_text,
            title=title,
            style=style,
            source_type=source_type,
            script_mode=script_mode,
        )
        return self._generate_non_streaming(
            prompt=prompt,
            empty_error="Ollama response did not include script text.",
        )

    def generate_title(
        self,
        *,
        script_text: str,
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        self.ensure_model_available()
        prompt = build_title_prompt(
            script_text,
            source_type=source_type,
            script_mode=script_mode,
        )
        generated = self._generate_non_streaming(
            prompt=prompt,
            empty_error="Ollama response did not include a title.",
        )
        return clean_generated_title(generated)

    def stream_rewrite(
        self,
        *,
        source_text: str,
        title: str | None = None,
        style: str = "podcast",
        source_type: str | None = None,
        script_mode: str = "single",
        on_chunk: Callable[[str], None],
    ) -> str:
        self.ensure_model_available()
        prompt = build_podcast_prompt(
            source_text,
            title=title,
            style=style,
            source_type=source_type,
            script_mode=script_mode,
        )
        chunks: list[str] = []
        try:
            with requests.post(
                f"{self._base_url}/generate",
                json={"model": self._model, "prompt": prompt, "stream": True},
                timeout=self._generate_timeout_seconds,
                stream=True,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    try:
                        payload = json.loads(raw_line)
                    except ValueError as exc:
                        raise RewriteProviderError(
                            "Ollama returned an invalid streaming chunk while generating text."
                        ) from exc
                    text = payload.get("response")
                    if isinstance(text, str) and text:
                        chunks.append(text)
                        on_chunk(text)
        except requests.ReadTimeout as exc:
            raise RewriteProviderError(
                f"Ollama timed out while generating text with model '{self._model}' "
                f"after {self._generate_timeout_seconds} seconds. "
                "This usually means the model is too slow for the current machine, "
                "the first run is still loading the model, or the source is large. "
                "Try increasing `OLLAMA_GENERATE_TIMEOUT_SECONDS`, warming the model "
                f"with `make test-ollama-local MODEL={self._model}`, or using a smaller model. "
                f"Details: {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise RewriteProviderError(
                f"Could not generate text with Ollama at {self._base_url}. "
                "Make sure Ollama is installed and running, then retry. "
                f"Details: {exc}"
            ) from exc

        text = "".join(chunks).strip()
        if not text:
            raise RewriteProviderError("Ollama response did not include script text.")
        return text

    def _generate_non_streaming(self, *, prompt: str, empty_error: str) -> str:
        try:
            response = requests.post(
                f"{self._base_url}/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=self._generate_timeout_seconds,
            )
            response.raise_for_status()
        except requests.ReadTimeout as exc:
            raise RewriteProviderError(
                f"Ollama timed out while generating text with model '{self._model}' "
                f"after {self._generate_timeout_seconds} seconds. "
                "This usually means the model is too slow for the current machine, "
                "the first run is still loading the model, or the source is large. "
                "Try increasing `OLLAMA_GENERATE_TIMEOUT_SECONDS`, warming the model "
                f"with `make test-ollama-local MODEL={self._model}`, or using a smaller model. "
                f"Details: {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise RewriteProviderError(
                f"Could not generate text with Ollama at {self._base_url}. "
                "Make sure Ollama is installed and running, then retry. "
                f"Details: {exc}"
            ) from exc
        payload = response.json()
        text = (payload.get("response") or "").strip()
        if not text:
            raise RewriteProviderError(empty_error)
        return text

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        timeout: int,
        operation: str,
    ) -> dict:
        url = f"{self._base_url}{path}"
        try:
            if method == "GET":
                response = requests.get(url, timeout=timeout)
            else:
                response = requests.post(url, json=json, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RewriteProviderError(
                f"Could not {operation} from Ollama at {self._base_url}. "
                "Make sure Ollama is installed and running on "
                "`http://localhost:11434`, then retry. "
                f"Details: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RewriteProviderError(
                f"Ollama returned a non-JSON response while trying to {operation}."
            ) from exc
        if not isinstance(payload, dict):
            raise RewriteProviderError(
                f"Ollama returned an unexpected response while trying to {operation}."
            )
        return payload
