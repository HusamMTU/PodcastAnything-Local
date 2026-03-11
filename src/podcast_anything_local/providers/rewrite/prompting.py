"""Prompt helpers for rewrite providers."""

from __future__ import annotations

from podcast_anything_local.providers.rewrite.base import RewriteProviderError

ESTIMATED_SPOKEN_WPM = 120
TARGET_AUDIO_MINUTES_MIN = 2
TARGET_AUDIO_MINUTES_MAX = 4
MIN_SPOKEN_WORDS = ESTIMATED_SPOKEN_WPM * TARGET_AUDIO_MINUTES_MIN
MAX_SPOKEN_WORDS = ESTIMATED_SPOKEN_WPM * TARGET_AUDIO_MINUTES_MAX
TITLE_INPUT_MAX_CHARS = 4_000


def build_podcast_prompt(
    source_text: str,
    *,
    title: str | None = None,
    style: str = "podcast",
    source_type: str | None = None,
    script_mode: str = "single",
) -> str:
    title_line = f"Title: {title}\n" if title else ""
    source_label = "YouTube transcript" if source_type == "youtube" else "source material"
    normalized_mode = script_mode.strip().lower()
    if normalized_mode == "single":
        mode_instruction = (
            "Rewrite it into a natural, single-host podcast script. Write only the words "
            "the host should say out loud. Do not include a 'Host:' label, titles, section "
            "headings, timestamps, music cues, sound-effect cues, or bracketed directions. "
            "Keep it engaging, clear, and structured with an intro, 3-5 short segments with "
            "signposts, and a concise outro. "
        )
    elif normalized_mode == "duo":
        mode_instruction = (
            "Rewrite it into a natural, two-host podcast dialogue between HOST_A and "
            "HOST_B. Write only spoken dialogue. Every spoken line must be prefixed with "
            "exactly 'HOST_A:' or 'HOST_B:'. Do not include titles, section headings, "
            "timestamps, music cues, sound-effect cues, or bracketed directions. "
            "Use HOST_A and HOST_B only as structural line labels, never as spoken names "
            "inside the dialogue itself. Do not write lines like 'I am HOST_A' or "
            "'HOST_B, what do you think?'. "
            "Do not wrap the speaker labels in markdown. Example format: "
            "HOST_A: Welcome back. HOST_B: Glad to be here. "
            "Keep it engaging, clear, and structured with an intro, 3-5 short segments "
            "with signposts, and a concise outro. "
        )
    else:
        raise RewriteProviderError("script_mode must be either 'single' or 'duo'.")

    return (
        "You are a podcast writer. "
        f"{mode_instruction}"
        f"Aim for {TARGET_AUDIO_MINUTES_MIN}-{TARGET_AUDIO_MINUTES_MAX} minutes of speech, "
        f"roughly {MIN_SPOKEN_WORDS}-{MAX_SPOKEN_WORDS} spoken words total. "
        f"Do not exceed about {MAX_SPOKEN_WORDS} spoken words. "
        "Use plain text only; do not include JSON, markdown, or stage directions. "
        "The output should be ready for text-to-speech without cleanup.\n\n"
        f"Style: {style}\n"
        f"Script Mode: {normalized_mode}\n"
        f"{title_line}"
        f"Input Type: {source_type or 'article'}\n"
        f"{source_label}:\n"
        f"{source_text}"
    )


def build_title_prompt(
    script_text: str,
    *,
    source_type: str | None = None,
    script_mode: str = "single",
) -> str:
    excerpt = script_text.strip()
    if len(excerpt) > TITLE_INPUT_MAX_CHARS:
        excerpt = excerpt[:TITLE_INPUT_MAX_CHARS].rstrip()
    return (
        "You are titling a podcast episode. "
        "Based on the script below, write one concise, compelling episode title. "
        "Return plain text only. Return only the title, with no quotes, no markdown, "
        "no speaker labels, and no extra explanation. Aim for 4-10 words.\n\n"
        f"Script Mode: {script_mode}\n"
        f"Input Type: {source_type or 'article'}\n"
        "Script:\n"
        f"{excerpt}"
    )


def clean_generated_title(raw_title: str) -> str:
    cleaned = raw_title.strip()
    if not cleaned:
        raise RewriteProviderError("Rewrite provider returned an empty title.")
    cleaned = cleaned.splitlines()[0].strip()
    cleaned = cleaned.removeprefix("Title:").removeprefix("title:").strip()
    cleaned = cleaned.strip("`*_#>\"' ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        raise RewriteProviderError("Rewrite provider returned an empty title.")
    if len(cleaned) > 120:
        cleaned = cleaned[:117].rstrip() + "..."
    return cleaned
