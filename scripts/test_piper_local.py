#!/usr/bin/env python3
"""Generate a local Piper sample through the project provider."""

from __future__ import annotations

import argparse
from pathlib import Path

from podcast_anything_local.core.config import load_settings
from podcast_anything_local.providers.tts.piper import PiperTTSProvider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a local Piper sample WAV file.")
    parser.add_argument(
        "--text",
        default="This is a local Piper synthesis test from Podcast Anything Local.",
        help="Text to synthesize.",
    )
    parser.add_argument(
        "--duo",
        action="store_true",
        help="Generate a two-host sample using host_a and host_b voice settings.",
    )
    parser.add_argument(
        "--host-a-text",
        default="Welcome back. This is the first host speaking through the local Piper setup.",
        help="Host A text used when --duo is enabled.",
    )
    parser.add_argument(
        "--host-b-text",
        default="And this is the second host, using the alternate Piper voice for duo mode.",
        help="Host B text used when --duo is enabled.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to the output WAV file.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_settings()
    provider = PiperTTSProvider(
        model_path=settings.piper_model_path,
        model_path_b=settings.piper_model_path_b,
        config_path=settings.piper_config_path,
        config_path_b=settings.piper_config_path_b,
        speaker_id=settings.piper_speaker_id,
        speaker_id_b=settings.piper_speaker_id_b,
    )

    if args.duo:
        if not settings.piper_model_path_b and not settings.piper_speaker_id_b:
            raise SystemExit(
                "Duo Piper test requires PIPER_MODEL_PATH_B or PIPER_SPEAKER_ID_B "
                "to be set so HOST_B uses a distinct voice."
            )
        segment_a = provider.synthesize(text=args.host_a_text, speaker="host_a")
        segment_b = provider.synthesize(text=args.host_b_text, speaker="host_b")
        audio = provider.join([segment_a, segment_b])
        default_output = "data/piper_voices/provider_test_duo.wav"
    else:
        audio = provider.synthesize(text=args.text, speaker="host_a")
        default_output = "data/piper_voices/provider_test.wav"

    output_path = Path(args.output or default_output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio.data)
    print(output_path)
    print(output_path.stat().st_size)


if __name__ == "__main__":
    main()
