"""Script rewrite orchestration."""

from __future__ import annotations

import re
import unicodedata

from podcast_anything_local.core.config import Settings
from podcast_anything_local.providers.rewrite.base import RewriteProvider, RewriteProviderError
from podcast_anything_local.providers.rewrite.openai_compatible import (
    OpenAICompatibleRewriteProvider,
)
from podcast_anything_local.providers.rewrite.prompting import (
    clean_generated_title,
    get_podcast_length_target,
)

_DUO_LABEL_RE = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z0-9 _-]{0,40})\s*:\s*(?P<text>.*)$")
_TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s*[–-]\s*\d{1,2}:\d{2})?\b")
_BLOCKED_DUO_LABELS = {
    "intro",
    "outro",
    "opening",
    "closing",
    "segment",
    "section",
    "part",
    "chapter",
    "break",
    "transition",
    "hook",
    "music",
    "sound",
    "sfx",
}
_HOST_A_LABELS = {
    "host_a",
    "host a",
    "host",
    "host 1",
    "speaker 1",
    "speaker a",
    "speaker one",
    "presenter 1",
    "presenter a",
    "narrator",
    "a",
}
_HOST_B_LABELS = {
    "host_b",
    "host b",
    "co-host",
    "co host",
    "cohost",
    "host 2",
    "speaker 2",
    "speaker b",
    "speaker two",
    "presenter 2",
    "presenter b",
    "guest",
    "b",
}
_MIN_DUO_TURNS = 4
_MIN_DUO_SPEAKER_CHANGES = 2
_SOURCE_CITATION_RE = re.compile(r"\[(?:\d+(?:\s*[-,–]\s*\d+)*)\]")
_SOURCE_MARKDOWN_TABLE_RE = re.compile(r"^\s*:?-{2,}:?(?:\s*\|\s*:?-{2,}:?)+\s*$")
_SOURCE_MAX_CHARS_SINGLE = 18_000
_SOURCE_MAX_CHARS_DUO = 12_000
_SOURCE_STOP_HEADINGS = {
    "references",
    "reference",
    "citations",
    "citation",
    "bibliography",
    "external links",
    "external link",
    "further reading",
    "see also",
    "notes",
    "footnotes",
}
_WORD_RE = re.compile(r"\b[\w']+\b")
_NORMALIZED_DUO_LINE_RE = re.compile(r"^(HOST_A|HOST_B):\s*(.*)$", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class RewriteService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def rewrite(
        self,
        *,
        source_text: str,
        title: str | None,
        style: str,
        source_type: str | None,
        script_mode: str,
        podcast_length: str,
    ) -> str:
        provider = self._build_provider()
        script = provider.rewrite(
            source_text=source_text,
            title=title,
            style=style,
            source_type=source_type,
            script_mode=script_mode,
            podcast_length=podcast_length,
        )
        cleaned = script.strip()
        if not cleaned:
            raise RewriteProviderError("Rewrite provider returned an empty script.")
        if script_mode == "duo":
            cleaned = _normalize_duo_script(cleaned)
        cleaned = _limit_script_to_target_duration(
            cleaned,
            script_mode=script_mode,
            podcast_length=podcast_length,
        )
        return cleaned

    def prepare_source_text(
        self,
        *,
        source_text: str,
        script_mode: str,
    ) -> tuple[str, dict[str, object]]:
        prepared, truncated = _prepare_source_text_for_rewrite(
            source_text,
            script_mode=script_mode,
        )
        return prepared, {
            "rewrite_input_char_count": len(prepared),
            "rewrite_input_truncated": truncated,
        }

    def generate_title(
        self,
        *,
        script_text: str,
        source_type: str | None,
        script_mode: str,
    ) -> str:
        provider = self._build_provider()
        generated = provider.generate_title(
            script_text=script_text,
            source_type=source_type,
            script_mode=script_mode,
        )
        return clean_generated_title(generated)

    def _build_provider(self) -> RewriteProvider:
        return OpenAICompatibleRewriteProvider(
            base_url=self._settings.openai_base_url,
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_model,
        )


def _normalize_duo_script(script_text: str) -> str:
    speaker_map: dict[str, str] = {}
    turns: list[tuple[str, str]] = []
    active_speaker: str | None = None
    active_lines: list[str] = []

    def flush() -> None:
        nonlocal active_lines
        if active_speaker and active_lines:
            merged = "\n".join(active_lines).strip()
            if merged:
                turns.append((active_speaker, merged))
        active_lines = []

    for raw_line in script_text.splitlines():
        stripped = _normalize_line(raw_line)
        if not stripped:
            if active_speaker and active_lines:
                active_lines.append("")
            continue

        match = _DUO_LABEL_RE.match(stripped)
        if match:
            label = _canonicalize_duo_label(match.group("label"), speaker_map=speaker_map)
            if label is None:
                continue
            flush()
            active_speaker = label
            content = match.group("text").strip()
            active_lines = [content] if content else []
            continue

        if active_speaker:
            active_lines.append(stripped)

    flush()

    if not turns:
        raise RewriteProviderError(
            "Duo rewrite did not contain recognizable speaker turns. "
            "Expected two-host dialogue that can be normalized to HOST_A: / HOST_B: lines."
        )

    speaker_set = {speaker for speaker, _ in turns}
    speaker_changes = sum(1 for index in range(1, len(turns)) if turns[index][0] != turns[index - 1][0])
    if (
        speaker_set != {"HOST_A", "HOST_B"}
        or len(turns) < _MIN_DUO_TURNS
        or speaker_changes < _MIN_DUO_SPEAKER_CHANGES
    ):
        raise RewriteProviderError(
            "Duo rewrite did not contain enough distinct speaker turns. "
            "Expected at least four HOST_A: / HOST_B: turns with both speakers participating."
        )

    normalized_turns: list[str] = []
    for speaker, turn_text in turns:
        lines = turn_text.splitlines()
        first_line = lines[0]
        normalized_turns.append(f"{speaker}: {first_line}".rstrip())
        normalized_turns.extend(lines[1:])

    return "\n".join(normalized_turns).strip()


def _prepare_source_text_for_rewrite(source_text: str, *, script_mode: str) -> tuple[str, bool]:
    normalized = unicodedata.normalize("NFKC", source_text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines: list[str] = []
    previous_line: str | None = None

    for raw_line in normalized.splitlines():
        cleaned = _clean_source_line(raw_line)
        if not cleaned:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        heading_key = cleaned.rstrip(":").strip().lower()
        if heading_key in _SOURCE_STOP_HEADINGS:
            break
        if _is_low_signal_source_line(cleaned):
            continue
        if cleaned == previous_line:
            continue
        cleaned_lines.append(cleaned)
        previous_line = cleaned

    cleaned_text = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()
    if not cleaned_text:
        cleaned_text = re.sub(r"\s+", " ", normalized).strip()

    max_chars = _SOURCE_MAX_CHARS_DUO if script_mode.strip().lower() == "duo" else _SOURCE_MAX_CHARS_SINGLE
    return _truncate_source_text(cleaned_text, max_chars=max_chars)


def _normalize_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*>\s*", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("*", "")
    cleaned = cleaned.replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean_source_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = _SOURCE_CITATION_RE.sub("", cleaned)
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[*\-•]\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -\t")


def _is_low_signal_source_line(line: str) -> bool:
    if _SOURCE_MARKDOWN_TABLE_RE.match(line):
        return True
    if line.count("|") >= 2:
        return True
    if re.fullmatch(r"https?://\S+", line):
        return True
    return False


def _truncate_source_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False

    units = [unit.strip() for unit in re.split(r"\n{2,}", text) if unit.strip()]
    if len(units) <= 1:
        units = [line.strip() for line in text.splitlines() if line.strip()]

    selected: list[str] = []
    total_length = 0
    for unit in units:
        separator_length = 2 if selected else 0
        projected = total_length + separator_length + len(unit)
        if projected > max_chars:
            if not selected:
                selected.append(unit[: _find_truncation_point(unit, max_chars)].rstrip())
            break
        selected.append(unit)
        total_length = projected

    prepared = "\n\n".join(selected).strip()
    if not prepared:
        prepared = text[: _find_truncation_point(text, max_chars)].rstrip()
    return prepared, True


def _find_truncation_point(text: str, max_chars: int) -> int:
    cutoff = min(len(text), max_chars)
    search_start = max(0, int(cutoff * 0.6))
    for marker in ("\n\n", ". ", "? ", "! ", "; "):
        index = text.rfind(marker, search_start, cutoff)
        if index != -1:
            return index + (0 if marker == "\n\n" else 1)
    return cutoff


def _limit_script_to_target_duration(
    script_text: str,
    *,
    script_mode: str,
    podcast_length: str,
) -> str:
    max_words = get_podcast_length_target(podcast_length).max_spoken_words
    if _count_script_words(script_text) <= max_words:
        return script_text

    if script_mode.strip().lower() == "duo":
        limited = _truncate_duo_script_to_word_budget(script_text, max_words=max_words)
    else:
        limited = _truncate_plain_text_to_word_budget(script_text, max_words=max_words)

    return limited or script_text


def _truncate_duo_script_to_word_budget(script_text: str, *, max_words: int) -> str:
    turns = _split_normalized_duo_script(script_text)
    if not turns:
        return _truncate_plain_text_to_word_budget(script_text, max_words=max_words)

    selected: list[tuple[str, str]] = []
    words_used = 0
    for speaker, turn_text in turns:
        remaining_words = max_words - words_used
        if remaining_words <= 0:
            break

        turn_word_count = _count_script_words(turn_text)
        if turn_word_count <= remaining_words:
            selected.append((speaker, turn_text))
            words_used += turn_word_count
            continue

        truncated_turn = _truncate_plain_text_to_word_budget(turn_text, max_words=remaining_words)
        if truncated_turn:
            selected.append((speaker, truncated_turn))
        break

    return "\n".join(f"{speaker}: {turn_text}" for speaker, turn_text in selected).strip()


def _split_normalized_duo_script(script_text: str) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    active_speaker: str | None = None
    active_lines: list[str] = []

    def flush() -> None:
        nonlocal active_lines
        if active_speaker and active_lines:
            merged = "\n".join(active_lines).strip()
            if merged:
                turns.append((active_speaker, merged))
        active_lines = []

    for raw_line in script_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if active_speaker and active_lines:
                active_lines.append("")
            continue

        match = _NORMALIZED_DUO_LINE_RE.match(stripped)
        if match:
            flush()
            active_speaker = match.group(1).upper()
            content = match.group(2).strip()
            active_lines = [content] if content else []
            continue

        if active_speaker:
            active_lines.append(stripped)

    flush()
    return turns


def _truncate_plain_text_to_word_budget(text: str, *, max_words: int) -> str:
    if max_words <= 0:
        return ""
    if _count_script_words(text) <= max_words:
        return text.strip()

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
    if not paragraphs:
        return _truncate_text_fragment(text, max_words=max_words)

    selected: list[str] = []
    words_used = 0
    for paragraph in paragraphs:
        remaining_words = max_words - words_used
        if remaining_words <= 0:
            break

        truncated_paragraph = _truncate_paragraph_to_word_budget(paragraph, max_words=remaining_words)
        if not truncated_paragraph:
            break
        selected.append(truncated_paragraph)
        words_used += _count_script_words(truncated_paragraph)
        if _count_script_words(truncated_paragraph) < _count_script_words(paragraph):
            break

    return "\n\n".join(selected).strip()


def _truncate_paragraph_to_word_budget(paragraph: str, *, max_words: int) -> str:
    if _count_script_words(paragraph) <= max_words:
        return paragraph.strip()

    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(paragraph.strip()) if sentence.strip()]
    if not sentences:
        return _truncate_text_fragment(paragraph, max_words=max_words)

    selected: list[str] = []
    words_used = 0
    for sentence in sentences:
        sentence_word_count = _count_script_words(sentence)
        if words_used + sentence_word_count <= max_words:
            selected.append(sentence)
            words_used += sentence_word_count
            continue

        if not selected:
            return _truncate_text_fragment(sentence, max_words=max_words)
        break

    return " ".join(selected).strip()


def _truncate_text_fragment(text: str, *, max_words: int) -> str:
    matches = list(_WORD_RE.finditer(text))
    if len(matches) <= max_words:
        return text.strip()
    cutoff = matches[max_words - 1].end()
    truncated = text[:cutoff].rstrip(" ,;:-")
    if truncated and truncated[-1] not in ".!?":
        truncated = f"{truncated}."
    return truncated.strip()


def _count_script_words(text: str) -> int:
    without_labels = re.sub(r"(?im)^\s*HOST_[AB]\s*:\s*", "", text)
    return len(_WORD_RE.findall(without_labels))


def _canonicalize_duo_label(label: str, *, speaker_map: dict[str, str]) -> str | None:
    cleaned = re.sub(r"\s+", " ", label.strip()).lower()
    if not cleaned or _TIMESTAMP_RE.search(cleaned):
        return None
    if cleaned in _BLOCKED_DUO_LABELS:
        return None
    if cleaned in _HOST_A_LABELS:
        return "HOST_A"
    if cleaned in _HOST_B_LABELS:
        return "HOST_B"
    if len(cleaned.split()) > 4:
        return None
    if cleaned in speaker_map:
        return speaker_map[cleaned]
    if len(speaker_map) == 0:
        speaker_map[cleaned] = "HOST_A"
        return "HOST_A"
    if len(speaker_map) == 1:
        speaker_map[cleaned] = "HOST_B"
        return "HOST_B"
    return None
