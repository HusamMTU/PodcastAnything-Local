"""Hierarchical multimodal PDF analysis for podcast script generation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from podcast_anything_local.core.config import Settings
from podcast_anything_local.providers.rewrite.openai_compatible import (
    OpenAICompatibleRewriteProvider,
)

_CHUNK_PAGES = 6
_CHUNK_OVERLAP_PAGES = 1


class DocumentPipelineError(RuntimeError):
    """Raised when multimodal document preparation fails."""


@dataclass(frozen=True, slots=True)
class PdfChunk:
    index: int
    page_start: int
    page_end: int
    page_numbers: tuple[int, ...]
    pdf_bytes: bytes


@dataclass(frozen=True, slots=True)
class DocumentAnalysisBundle:
    page_count: int
    chunks: list[PdfChunk]
    chunk_summaries: list[dict[str, object]]
    document_map: dict[str, object]


class MultimodalDocumentService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider_factory: Callable[[], OpenAICompatibleRewriteProvider] | None = None,
    ) -> None:
        self._settings = settings
        self._provider_factory = provider_factory or self._build_provider

    def should_use(
        self,
        *,
        source_type: str | None,
        source_file_path: str | None,
    ) -> bool:
        return (
            (source_type or "").strip().lower() == "pdf"
            and bool(source_file_path)
        )

    def analyze_pdf_document(
        self,
        *,
        source_file_path: str,
        title: str | None,
        script_mode: str,
    ) -> DocumentAnalysisBundle:
        pdf_path = Path(source_file_path)
        if not pdf_path.is_file():
            raise DocumentPipelineError(f"PDF source file not found: {source_file_path}")

        provider = self._provider_factory()

        chunks = _build_pdf_chunks(pdf_path)
        if not chunks:
            raise DocumentPipelineError("No readable pages were found in the PDF document.")

        chunk_summaries: list[dict[str, object]] = []
        for chunk in chunks:
            summary = provider.summarize_pdf_chunk(
                pdf_bytes=chunk.pdf_bytes,
                filename=f"{pdf_path.stem}_pages_{chunk.page_start:03d}_{chunk.page_end:03d}.pdf",
                title=title,
                chunk_index=chunk.index,
                chunk_count=len(chunks),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                script_mode=script_mode,
            )
            chunk_summaries.append(summary)

        document_map = provider.build_document_map(
            chunk_summaries=chunk_summaries,
            title=title,
            script_mode=script_mode,
        )

        return DocumentAnalysisBundle(
            page_count=_count_pdf_pages(pdf_path),
            chunks=chunks,
            chunk_summaries=chunk_summaries,
            document_map=document_map,
        )

    def build_podcast_plan(
        self,
        *,
        document_map: dict[str, object],
        title: str | None,
        script_mode: str,
    ) -> dict[str, object]:
        provider = self._provider_factory()
        return provider.build_podcast_plan(
            document_map=document_map,
            title=title,
            script_mode=script_mode,
        )

    def build_rewrite_source_text(
        self,
        *,
        analysis: DocumentAnalysisBundle,
        podcast_plan: dict[str, object],
    ) -> str:
        lines: list[str] = []
        working_title = _string_value(podcast_plan.get("working_title"))
        if working_title:
            lines.append(f"Working title: {working_title}")
        audience = _string_value(podcast_plan.get("audience"))
        if audience:
            lines.append(f"Audience: {audience}")
        angle = _string_value(podcast_plan.get("angle"))
        if angle:
            lines.append(f"Angle: {angle}")

        lines.append("")
        lines.append("Episode plan:")
        intro = _string_value(podcast_plan.get("intro"))
        if intro:
            lines.append(f"Intro: {intro}")
        outro = _string_value(podcast_plan.get("outro"))
        if outro:
            lines.append(f"Outro: {outro}")

        for index, segment in enumerate(_list_of_dicts(podcast_plan.get("segments")), start=1):
            lines.append(f"Segment {index}: {_string_value(segment.get('name')) or 'Untitled'}")
            purpose = _string_value(segment.get("purpose"))
            if purpose:
                lines.append(f"Purpose: {purpose}")
            beats = _list_of_strings(segment.get("beats"))
            if beats:
                lines.append("Beats:")
                lines.extend(f"- {beat}" for beat in beats)
            source_pages = _list_of_ints(segment.get("source_pages"))
            if source_pages:
                lines.append(f"Source pages: {', '.join(str(page) for page in source_pages)}")

        must_include = _list_of_strings(podcast_plan.get("must_include"))
        if must_include:
            lines.append("")
            lines.append("Must include:")
            lines.extend(f"- {item}" for item in must_include)

        lines.append("")
        lines.append("Document map:")
        for heading, key in (
            ("Overall summary", "overall_summary"),
            ("Narrative arc", "narrative_arc"),
            ("Visual takeaways", "visual_takeaways"),
            ("Must include details", "must_include"),
            ("Supporting details", "supporting_details"),
            ("Caveats", "caveats"),
        ):
            value = analysis.document_map.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"{heading}: {value.strip()}")
            else:
                items = _list_of_strings(value)
                if items:
                    lines.append(f"{heading}:")
                    lines.extend(f"- {item}" for item in items)

        lines.append("")
        lines.append("Chunk evidence:")
        for summary in analysis.chunk_summaries:
            page_start = summary.get("page_start")
            page_end = summary.get("page_end")
            lines.append(f"Pages {page_start}-{page_end}: {_string_value(summary.get('summary')) or ''}".rstrip())
            key_points = _list_of_strings(summary.get("key_points"))
            for item in key_points[:4]:
                lines.append(f"- {item}")
            visuals = _list_of_strings(summary.get("visual_elements"))
            for item in visuals[:2]:
                lines.append(f"- Visual: {item}")

        return "\n".join(line for line in lines if line is not None).strip()

    def build_artifacts(
        self,
        *,
        analysis: DocumentAnalysisBundle,
    ) -> dict[str, str]:
        page_index = {
            "page_count": analysis.page_count,
            "chunks": [
                {
                    "chunk_index": chunk.index,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "page_numbers": list(chunk.page_numbers),
                }
                for chunk in analysis.chunks
            ],
        }
        artifacts: dict[str, str] = {
            "page_index.json": json.dumps(page_index, ensure_ascii=True, indent=2),
            "document_map.json": json.dumps(analysis.document_map, ensure_ascii=True, indent=2),
        }
        for index, summary in enumerate(analysis.chunk_summaries, start=1):
            artifacts[f"chunk_{index:03d}_summary.json"] = json.dumps(
                summary, ensure_ascii=True, indent=2
            )
        return artifacts

    def build_plan_artifacts(
        self,
        *,
        podcast_plan: dict[str, object],
        rewrite_source_text: str,
    ) -> dict[str, str]:
        return {
            "podcast_plan.json": json.dumps(podcast_plan, ensure_ascii=True, indent=2),
            "rewrite_input.txt": rewrite_source_text,
        }

    def build_metadata(
        self,
        *,
        analysis: DocumentAnalysisBundle,
    ) -> dict[str, object]:
        return {
            "multimodal_document_pipeline": True,
            "multimodal_document_page_count": analysis.page_count,
            "multimodal_document_chunk_count": len(analysis.chunks),
            "multimodal_document_chunk_pages": _CHUNK_PAGES,
            "multimodal_document_chunk_overlap_pages": _CHUNK_OVERLAP_PAGES,
        }

    def _build_provider(self) -> OpenAICompatibleRewriteProvider:
        return OpenAICompatibleRewriteProvider(
            base_url=self._settings.openai_base_url,
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_model,
        )


def _count_pdf_pages(pdf_path: Path) -> int:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:  # pragma: no cover
        raise DocumentPipelineError(f"Failed to parse PDF document: {exc}") from exc
    return len(reader.pages)


def _build_pdf_chunks(pdf_path: Path) -> list[PdfChunk]:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:  # pragma: no cover
        raise DocumentPipelineError(f"Failed to parse PDF document: {exc}") from exc

    total_pages = len(reader.pages)
    if total_pages == 0:
        return []

    chunks: list[PdfChunk] = []
    start_index = 0
    chunk_index = 1
    while start_index < total_pages:
        end_index = min(start_index + _CHUNK_PAGES, total_pages)
        writer = PdfWriter()
        for page_index in range(start_index, end_index):
            writer.add_page(reader.pages[page_index])
        buffer = BytesIO()
        writer.write(buffer)
        chunks.append(
            PdfChunk(
                index=chunk_index,
                page_start=start_index + 1,
                page_end=end_index,
                page_numbers=tuple(range(start_index + 1, end_index + 1)),
                pdf_bytes=buffer.getvalue(),
            )
        )
        if end_index >= total_pages:
            break
        start_index = end_index - _CHUNK_OVERLAP_PAGES
        chunk_index += 1
    return chunks


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _list_of_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    ints: list[int] = []
    for item in value:
        if isinstance(item, int):
            ints.append(item)
    return ints


def _string_value(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None
