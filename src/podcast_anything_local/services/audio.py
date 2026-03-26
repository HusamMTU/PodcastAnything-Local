"""Audio synthesis orchestration."""

from __future__ import annotations

import re
from collections.abc import Callable

from podcast_anything_local.core.config import Settings
from podcast_anything_local.providers.tts.base import SynthesizedAudio, TTSProvider, TTSProviderError
from podcast_anything_local.providers.tts.elevenlabs import ElevenLabsTTSProvider
from podcast_anything_local.providers.tts.openai import OpenAITTSProvider
from podcast_anything_local.providers.tts.wave import WaveTTSProvider

_DUO_LINE_RE = re.compile(r"^\s*(HOST_A|HOST_B)\s*:\s*(.*)$", re.IGNORECASE)
_SINGLE_SPEAKER_LABEL_RE = re.compile(
    r"^\s*(?:host|co-host|narrator|speaker(?:\s+\d+)?|host_a|host_b)\s*:\s*",
    re.IGNORECASE,
)
_TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s*[–-]\s*\d{1,2}:\d{2})?\b")
_STAGE_DIRECTION_ONLY_RE = re.compile(r"^\s*(?:\[[^\]]+\]|\([^)]*\)|\{[^}]+\})\s*$")
_INLINE_BRACKETED_RE = re.compile(r"\[[^\]]+\]")
_INLINE_STAGE_PARENS_RE = re.compile(
    r"\((?:[^)]*\b(?:music|sound|sfx|pause|beat|laughs?|sighs?|applause|"
    r"fade(?:s|d)?\s+(?:in|out)|intro|outro|stinger|transition)[^)]*)\)",
    re.IGNORECASE,
)
_SHORT_SECTION_RE = re.compile(
    r"^(?:intro|outro|opening|closing|segment|section|part|chapter|break|transition|hook)\b",
    re.IGNORECASE,
)
_MUSIC_CUE_RE = re.compile(
    r"\b(?:music|sound effect|sound effects|sfx|stinger|theme|applause|"
    r"fade(?:s|d)?\s+(?:in|out)|transition sting)\b",
    re.IGNORECASE,
)
_SENTENCE_PUNCTUATION_RE = re.compile(r"[.!?]")
_HOST_PLACEHOLDER_RE = re.compile(r"\bHOST_[AB]\b", re.IGNORECASE)
_SELF_HOST_INTRO_RE = re.compile(
    r"\b((?:i(?:'m| am)|this is)\s+(?:your\s+)?host)\s+(HOST_[AB])\b",
    re.IGNORECASE,
)
_COHOST_INTRO_RE = re.compile(
    r"\b((?:joining me(?:\s+today)?\s+is|with me(?:\s+today)?\s+is))\s+(HOST_[AB])\b",
    re.IGNORECASE,
)


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(
        self,
        *,
        script_text: str,
        script_mode: str,
        provider_name: str | None,
        voice_id: str | None,
        voice_id_b: str | None,
        on_stream_start: Callable[[str, str], None] | None = None,
        on_stream_chunk: Callable[[bytes], None] | None = None,
        on_preview_segment: Callable[[SynthesizedAudio, int], None] | None = None,
    ) -> SynthesizedAudio:
        resolved_provider_name = provider_name or self._settings.tts_provider
        normalized_provider_name = resolved_provider_name.strip().lower()
        if script_mode == "duo" and normalized_provider_name == "elevenlabs":
            return self._synthesize_elevenlabs_duo(
                script_text=script_text,
                voice_id=voice_id,
                voice_id_b=voice_id_b,
                on_stream_start=on_stream_start,
                on_stream_chunk=on_stream_chunk,
            )
        provider = self._build_provider(normalized_provider_name)
        if script_mode == "duo":
            host_a_voice, host_b_voice = self._resolve_duo_voices(
                provider_name=normalized_provider_name,
                voice_id=voice_id,
                voice_id_b=voice_id_b,
            )

            turns = _parse_duo_turns(script_text)
            if not turns:
                raise TTSProviderError(
                    "script_mode=duo requires script lines prefixed with HOST_A: or HOST_B:."
                )
            segments: list[SynthesizedAudio] = []
            for index, (speaker, turn_text) in enumerate(turns, start=1):
                segment = provider.synthesize(
                    text=turn_text,
                    voice_id=host_a_voice if speaker == "HOST_A" else host_b_voice,
                    speaker="host_a" if speaker == "HOST_A" else "host_b",
                )
                segments.append(segment)
                if normalized_provider_name == "openai" and on_preview_segment is not None:
                    on_preview_segment(segment, index)
            return provider.join(segments)

        host_a_voice = self._resolve_single_voice(
            provider_name=normalized_provider_name,
            voice_id=voice_id,
        )

        spoken_text = _sanitize_single_host_script(script_text)
        if not spoken_text:
            raise TTSProviderError("No spoken text remained after cleaning the single-host script.")
        if (
            on_stream_start is not None
            and on_stream_chunk is not None
            and hasattr(provider, "supports_live_streaming")
            and provider.supports_live_streaming()
        ):
            on_stream_start(provider.live_stream_content_type(), provider.live_stream_file_name())
            return provider.stream_synthesize(
                text=spoken_text,
                voice_id=host_a_voice,
                speaker="host_a",
                on_chunk=on_stream_chunk,
            )
        return provider.synthesize(text=spoken_text, voice_id=host_a_voice, speaker="host_a")

    def _synthesize_elevenlabs_duo(
        self,
        *,
        script_text: str,
        voice_id: str | None,
        voice_id_b: str | None,
        on_stream_start: Callable[[str, str], None] | None = None,
        on_stream_chunk: Callable[[bytes], None] | None = None,
    ) -> SynthesizedAudio:
        provider = ElevenLabsTTSProvider(
            api_key=self._settings.elevenlabs_api_key,
            model_id=self._settings.elevenlabs_model_id,
            dialogue_model_id=self._settings.elevenlabs_dialogue_model_id,
            output_format=self._settings.elevenlabs_output_format,
        )
        host_a_voice, host_b_voice = self._resolve_duo_voices(
            provider_name="elevenlabs",
            voice_id=voice_id,
            voice_id_b=voice_id_b,
        )
        turns = _parse_duo_turns(script_text)
        if not turns:
            raise TTSProviderError(
                "script_mode=duo requires script lines prefixed with HOST_A: or HOST_B:."
            )
        if (
            on_stream_start is not None
            and on_stream_chunk is not None
            and provider.supports_live_streaming()
        ):
            on_stream_start(provider.live_stream_content_type(), provider.live_stream_file_name())
            return provider.stream_synthesize_dialogue(
                turns=turns,
                voice_id_a=host_a_voice,
                voice_id_b=host_b_voice,
                on_chunk=on_stream_chunk,
            )
        return provider.synthesize_dialogue(
            turns=turns,
            voice_id_a=host_a_voice,
            voice_id_b=host_b_voice,
        )

    def _build_provider(self, provider_name: str) -> TTSProvider:
        normalized = provider_name.strip().lower()
        if normalized == "wave":
            return WaveTTSProvider()
        if normalized == "elevenlabs":
            return ElevenLabsTTSProvider(
                api_key=self._settings.elevenlabs_api_key,
                model_id=self._settings.elevenlabs_model_id,
                dialogue_model_id=self._settings.elevenlabs_dialogue_model_id,
                output_format=self._settings.elevenlabs_output_format,
            )
        if normalized == "openai":
            return OpenAITTSProvider(
                base_url=self._settings.openai_base_url,
                api_key=self._settings.openai_api_key,
                model=self._settings.openai_tts_model,
                response_format=self._settings.openai_tts_response_format,
            )
        raise TTSProviderError(f"Unsupported TTS provider: {provider_name}")

    def _resolve_single_voice(self, *, provider_name: str, voice_id: str | None) -> str | None:
        if provider_name == "wave":
            return voice_id or "host_a"
        if provider_name == "elevenlabs":
            return voice_id or self._settings.elevenlabs_voice_id
        if provider_name == "openai":
            return voice_id or self._settings.openai_tts_voice
        return voice_id

    def _resolve_duo_voices(
        self,
        *,
        provider_name: str,
        voice_id: str | None,
        voice_id_b: str | None,
    ) -> tuple[str | None, str | None]:
        if provider_name == "wave":
            return voice_id or "host_a", voice_id_b or "host_b"
        if provider_name == "elevenlabs":
            return voice_id or self._settings.elevenlabs_voice_id, (
                voice_id_b or self._settings.elevenlabs_voice_id_b
            )
        if provider_name == "openai":
            return voice_id or self._settings.openai_tts_voice, (
                voice_id_b or self._settings.openai_tts_voice_b
            )
        return voice_id, voice_id_b


def _parse_duo_turns(script_text: str) -> list[tuple[str, str]]:
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

        normalized = _normalize_script_line(raw_line)
        match = _DUO_LINE_RE.match(normalized)
        if match:
            flush()
            active_speaker = match.group(1).upper()
            content = _clean_spoken_line(match.group(2), strip_single_host_label=False)
            content = _clean_duo_placeholder_tokens(content, speaker=active_speaker)
            active_lines = [content] if content else []
            continue

        if active_speaker:
            cleaned = _clean_spoken_line(normalized, strip_single_host_label=False)
            cleaned = _clean_duo_placeholder_tokens(cleaned, speaker=active_speaker)
            if cleaned:
                active_lines.append(cleaned)

    flush()
    return turns


def _sanitize_single_host_script(script_text: str) -> str:
    spoken_lines: list[str] = []

    for raw_line in script_text.splitlines():
        if not raw_line.strip():
            if spoken_lines and spoken_lines[-1] != "":
                spoken_lines.append("")
            continue

        cleaned = _clean_spoken_line(raw_line)
        if cleaned:
            spoken_lines.append(cleaned)

    return _join_spoken_lines(spoken_lines)


def _normalize_script_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*>\s*", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("*", "")
    cleaned = cleaned.replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean_spoken_line(line: str, *, strip_single_host_label: bool = True) -> str | None:
    cleaned = _normalize_script_line(line)
    if not cleaned:
        return None

    if strip_single_host_label:
        cleaned = _SINGLE_SPEAKER_LABEL_RE.sub("", cleaned).strip()
        if not cleaned:
            return None

    if _STAGE_DIRECTION_ONLY_RE.match(cleaned):
        return None

    cleaned = _INLINE_BRACKETED_RE.sub(" ", cleaned)
    cleaned = _INLINE_STAGE_PARENS_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\t")
    if not cleaned:
        return None

    compact = cleaned.rstrip(":").strip()
    if not compact:
        return None

    if _TIMESTAMP_RE.search(compact) and len(compact) <= 80:
        return None
    if (
        _SHORT_SECTION_RE.match(compact)
        and len(compact.split()) <= 8
        and not _SENTENCE_PUNCTUATION_RE.search(compact)
    ):
        return None
    if _MUSIC_CUE_RE.search(compact) and len(compact) <= 80:
        return None
    if cleaned.endswith(":") and len(cleaned) <= 40:
        return None

    return cleaned


def _join_spoken_lines(lines: list[str]) -> str:
    merged: list[str] = []
    for line in lines:
        if line == "":
            if merged and merged[-1] != "":
                merged.append("")
            continue
        merged.append(line)

    while merged and merged[0] == "":
        merged.pop(0)
    while merged and merged[-1] == "":
        merged.pop()
    return "\n".join(merged).strip()


def _clean_duo_placeholder_tokens(text: str | None, *, speaker: str) -> str | None:
    if not text:
        return text

    other_speaker = "HOST_B" if speaker == "HOST_A" else "HOST_A"
    cleaned = _SELF_HOST_INTRO_RE.sub(
        lambda match: match.group(1) if match.group(2).upper() == speaker else match.group(0),
        text,
    )
    cleaned = _COHOST_INTRO_RE.sub(
        lambda match: f"{match.group(1)} my co-host"
        if match.group(2).upper() == other_speaker
        else match.group(0),
        cleaned,
    )
    cleaned = re.sub(rf"\b{other_speaker}\b", "my co-host", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\b{speaker}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\t")
    if not cleaned or not _HOST_PLACEHOLDER_RE.search(cleaned):
        return cleaned or None
    cleaned = _HOST_PLACEHOLDER_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\t")
    return cleaned or None
