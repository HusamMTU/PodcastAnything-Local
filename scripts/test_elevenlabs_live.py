#!/usr/bin/env python3
"""Run a real ElevenLabs TTS smoke test through the project provider."""

from __future__ import annotations

import argparse
from pathlib import Path

from podcast_anything_local.core.config import load_settings
from podcast_anything_local.providers.tts.elevenlabs import ElevenLabsTTSProvider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live ElevenLabs TTS smoke test.")
    parser.add_argument(
        "--duo",
        action="store_true",
        help="Generate a two-speaker sample through ElevenLabs dialogue mode.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path override. Defaults under data/ based on the returned audio format.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_settings()
    if not settings.elevenlabs_api_key:
        raise SystemExit(
            "ELEVENLABS_API_KEY is not set. Add it to the environment or .env, then retry."
        )
    if not settings.elevenlabs_voice_id:
        raise SystemExit(
            "ELEVENLABS_VOICE_ID is not set. Add it to the environment or .env, then retry."
        )
    if args.duo and not settings.elevenlabs_voice_id_b:
        raise SystemExit(
            "ELEVENLABS_VOICE_ID_B is required for --duo. Add it to the environment or .env, then retry."
        )

    provider = ElevenLabsTTSProvider(
        api_key=settings.elevenlabs_api_key,
        model_id=settings.elevenlabs_model_id,
        dialogue_model_id=settings.elevenlabs_dialogue_model_id,
        output_format=settings.elevenlabs_output_format,
    )

    if args.duo:
        audio = provider.synthesize_dialogue(
            turns=[
                (
                    "HOST_A",
                    "Welcome back. This smoke test checks the first ElevenLabs host voice.",
                ),
                (
                    "HOST_B",
                    "And this line checks the second ElevenLabs host voice and the dialogue path.",
                ),
            ],
            voice_id_a=settings.elevenlabs_voice_id,
            voice_id_b=settings.elevenlabs_voice_id_b,
        )
    else:
        audio = provider.synthesize(
            text=(
                "This smoke test verifies that ElevenLabs text to speech is configured correctly "
                "for Podcast Anything Local."
            ),
            voice_id=settings.elevenlabs_voice_id,
            speaker="host_a",
        )

    output_path = _resolve_output_path(args.output, audio.file_name, is_duo=args.duo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio.data)
    print(output_path)
    print(output_path.stat().st_size)


def _resolve_output_path(output: str | None, file_name: str, *, is_duo: bool) -> Path:
    if output:
        candidate = Path(output).expanduser().resolve()
        if candidate.suffix:
            return candidate
        suffix = Path(file_name).suffix
        return candidate.with_suffix(suffix)

    default_name = "elevenlabs_tts_duo_test" if is_duo else "elevenlabs_tts_test"
    suffix = Path(file_name).suffix
    return Path("data").resolve() / f"{default_name}{suffix}"


if __name__ == "__main__":
    main()
