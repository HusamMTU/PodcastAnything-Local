"""Prompt helpers for rewrite providers."""

from __future__ import annotations

import json
from dataclasses import dataclass

from podcast_anything_local.providers.rewrite.base import RewriteProviderError

ESTIMATED_SPOKEN_WPM = 120
TITLE_INPUT_MAX_CHARS = 4_000
DEFAULT_PODCAST_LENGTH = "medium"


@dataclass(frozen=True, slots=True)
class PodcastLengthTarget:
    preset: str
    min_minutes: int
    max_minutes: int

    @property
    def min_spoken_words(self) -> int:
        return ESTIMATED_SPOKEN_WPM * self.min_minutes

    @property
    def max_spoken_words(self) -> int:
        return ESTIMATED_SPOKEN_WPM * self.max_minutes

    @property
    def duration_label(self) -> str:
        return f"{self.min_minutes}-{self.max_minutes} minutes"


_PODCAST_LENGTH_TARGETS = {
    "short": PodcastLengthTarget("short", 2, 3),
    "medium": PodcastLengthTarget("medium", 4, 5),
    "long": PodcastLengthTarget("long", 6, 10),
}
SUPPORTED_PODCAST_LENGTHS = tuple(_PODCAST_LENGTH_TARGETS.keys())
MAX_SPOKEN_WORDS = _PODCAST_LENGTH_TARGETS[DEFAULT_PODCAST_LENGTH].max_spoken_words


def get_podcast_length_target(podcast_length: str | None) -> PodcastLengthTarget:
    normalized = (podcast_length or DEFAULT_PODCAST_LENGTH).strip().lower()
    try:
        return _PODCAST_LENGTH_TARGETS[normalized]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_PODCAST_LENGTHS)
        raise RewriteProviderError(f"podcast_length must be one of: {supported}") from exc


def build_podcast_prompt(
    source_text: str,
    *,
    title: str | None = None,
    style: str = "podcast",
    source_type: str | None = None,
    script_mode: str = "single",
    podcast_length: str = DEFAULT_PODCAST_LENGTH,
) -> str:
    target = get_podcast_length_target(podcast_length)
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
        f"Aim for {target.duration_label} of speech, "
        f"roughly {target.min_spoken_words}-{target.max_spoken_words} spoken words total. "
        f"Do not exceed about {target.max_spoken_words} spoken words. "
        "Use plain text only; do not include JSON, markdown, or stage directions. "
        "The output should be ready for text-to-speech without cleanup.\n\n"
        f"Style: {style}\n"
        f"Script Mode: {normalized_mode}\n"
        f"Podcast Length: {target.preset}\n"
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
            f"\n\nSupplemental extracted text for these pages:\n{supplemental_text.strip()}"
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
    podcast_length: str = DEFAULT_PODCAST_LENGTH,
) -> str:
    target = get_podcast_length_target(podcast_length)
    title_line = f"Document title: {title}\n" if title else ""
    return (
        f"You are planning a {target.duration_label} podcast episode based on a structured document map. "
        "Return JSON only.\n\n"
        f"{title_line}"
        f"Podcast mode: {script_mode}\n\n"
        f"Podcast length: {target.preset}\n\n"
        "Document map JSON:\n"
        f"{json.dumps(document_map, ensure_ascii=True, indent=2)}"
    )
