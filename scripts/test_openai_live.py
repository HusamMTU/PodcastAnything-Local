#!/usr/bin/env python3
"""Run a real OpenAI rewrite smoke test through the project provider."""

from __future__ import annotations

import argparse
from pathlib import Path

from podcast_anything_local.core.config import load_settings
from podcast_anything_local.providers.rewrite.openai_compatible import (
    OpenAICompatibleRewriteProvider,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live OpenAI rewrite smoke test.")
    parser.add_argument(
        "--model",
        default=None,
        help="Optional OpenAI model override.",
    )
    parser.add_argument(
        "--output",
        default="data/openai_rewrite_test.txt",
        help="Path to the output text file for the sample rewrite.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_settings()
    if not settings.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Add it to the environment or .env, then retry."
        )

    model = args.model or settings.openai_model
    provider = OpenAICompatibleRewriteProvider(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=model,
    )

    script = provider.rewrite(
        source_text=(
            "This smoke test verifies that the hosted rewrite provider can turn a short source "
            "into a concise podcast script and that the repo is configured correctly for OpenAI."
        ),
        title="OpenAI Rewrite Smoke Test",
        style="podcast",
        source_type="text",
        script_mode="single",
    )
    title = provider.generate_title(
        script_text=script,
        source_type="text",
        script_mode="single",
    )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"{title}\n\n{script}\n",
        encoding="utf-8",
    )
    print(output_path)
    print(output_path.stat().st_size)


if __name__ == "__main__":
    main()
