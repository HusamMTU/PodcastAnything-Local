#!/usr/bin/env python3
"""Check local Ollama setup and generate a sample rewrite."""

from __future__ import annotations

import argparse
from pathlib import Path

from podcast_anything_local.core.config import load_settings
from podcast_anything_local.providers.rewrite.ollama import OllamaRewriteProvider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a local Ollama setup and run a sample rewrite.")
    parser.add_argument(
        "--model",
        default=None,
        help="Optional Ollama model override.",
    )
    parser.add_argument(
        "--pull-if-missing",
        action="store_true",
        help="Pull the configured model through the Ollama API if it is missing.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify connectivity and model availability.",
    )
    parser.add_argument(
        "--output",
        default="data/ollama_rewrite_test.txt",
        help="Path to the output text file for the sample rewrite.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_settings()
    model = args.model or settings.ollama_model
    provider = OllamaRewriteProvider(
        base_url=settings.ollama_base_url,
        model=model,
        generate_timeout_seconds=settings.ollama_generate_timeout_seconds,
    )

    try:
        provider.ensure_model_available(pull_if_missing=args.pull_if_missing)
    except Exception as exc:
        raise SystemExit(
            "Ollama setup check failed.\n"
            "Install Ollama from https://ollama.com/download/mac or use the official install script, "
            "start it locally with `open -a /Applications/Ollama.app --args hidden`, then retry.\n"
            f"Details: {exc}"
        ) from exc

    available_models = provider.list_models()
    print(f"Ollama base URL: {settings.ollama_base_url}")
    print(f"Ollama model: {model}")
    print(f"Generate timeout: {settings.ollama_generate_timeout_seconds}s")
    print(f"Available models: {len(available_models)}")

    if args.check_only:
        return

    script = provider.rewrite(
        source_text=(
            "Local models let this project rewrite a source into a podcast script without "
            "a cloud dependency. The goal of this smoke test is to verify the Ollama API, "
            "the configured model, and our rewrite provider end to end."
        ),
        title="Local Ollama Rewrite Test",
        style="podcast",
        source_type="text",
        script_mode="single",
    )
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(script, encoding="utf-8")
    print(output_path)
    print(output_path.stat().st_size)


if __name__ == "__main__":
    main()
