"""Prompt helpers for rewrite providers."""

from __future__ import annotations

import json

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


def build_pdf_chunk_summary_prompt(
    *,
    title: str | None,
    chunk_index: int,
    chunk_count: int,
    page_start: int,
    page_end: int,
    script_mode: str,
    supplemental_text: str | None = None,
) -> str:
    title_line = f"Document title: {title}\n" if title else ""
    supplemental_section = ""
    if supplemental_text and supplemental_text.strip():
        supplemental_section = (
            "\n\nSupplemental extracted text for these pages:\n"
            f"{supplemental_text.strip()}"
        )
    return (
        "You are analyzing one chunk of a longer source document for a podcast adaptation. "
        "Review the PDF pages carefully, including both text and visuals. Return JSON only.\n\n"
        f"{title_line}"
        f"Chunk: {chunk_index} of {chunk_count}\n"
        f"Pages: {page_start}-{page_end}\n"
        f"Podcast mode: {script_mode}\n\n"
        "Focus on the material that matters for a short podcast episode. Capture the key ideas, "
        "important facts, meaningful visuals, and the best angles for spoken explanation."
        f"{supplemental_section}"
    )


def build_document_map_prompt(
    *,
    chunk_summaries: list[dict[str, object]],
    title: str | None,
    script_mode: str,
) -> str:
    title_line = f"Document title: {title}\n" if title else ""
    return (
        "You are combining chunk-level document summaries into one structured document map for a "
        "podcast adaptation. Return JSON only.\n\n"
        f"{title_line}"
        f"Podcast mode: {script_mode}\n\n"
        "Chunk summaries JSON:\n"
        f"{json.dumps(chunk_summaries, ensure_ascii=True, indent=2)}"
    )


def build_podcast_plan_prompt(
    *,
    document_map: dict[str, object],
    title: str | None,
    script_mode: str,
) -> str:
    title_line = f"Document title: {title}\n" if title else ""
    return (
        "You are planning a 2-4 minute podcast episode based on a structured document map. "
        "Return JSON only.\n\n"
        f"{title_line}"
        f"Podcast mode: {script_mode}\n\n"
        "Document map JSON:\n"
        f"{json.dumps(document_map, ensure_ascii=True, indent=2)}"
    )
