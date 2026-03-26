"""Hierarchical multimodal document analysis for podcast script generation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from podcast_anything_local.core.config import Settings
from podcast_anything_local.providers.rewrite.openai_compatible import (
    OpenAICompatibleRewriteProvider,
)

try:
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.units import inch
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
except ModuleNotFoundError:  # pragma: no cover
    canvas = None
    letter = None
    landscape = None
    inch = None
    stringWidth = None

_CHUNK_PAGES = 6
_CHUNK_OVERLAP_PAGES = 1
_SLIDE_HEADER_RE = re.compile(r"^Slide\s+(?P<number>\d+)(?::\s*(?P<title>.*))?$")
_BODY_FONT = "Helvetica"
_BODY_FONT_SIZE = 11.0
_BODY_LEADING = 15.0
_HEADER_FONT = "Helvetica-Bold"
_HEADER_FONT_SIZE = 18.0
_HEADER_LEADING = 22.0
_SECTION_FONT = "Helvetica-Bold"
_SECTION_FONT_SIZE = 12.0
_SECTION_LEADING = 16.0
_SPACER_LEADING = 10.0


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
class PreparedDocumentBundle:
    analysis_pdf_path: str | None
    analysis_pdf_bytes: bytes | None
    analysis_display_name: str
    analysis_artifact_name: str | None
    page_context: dict[int, str]
    text_artifacts: dict[str, str]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class SlideContent:
    slide_number: int
    title: str
    body_lines: tuple[str, ...]
    notes_text: str | None


@dataclass(frozen=True, slots=True)
class RenderedLine:
    text: str
    font_name: str
    font_size: float
    leading: float


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
        normalized = (source_type or "").strip().lower()
        return normalized in {"pdf", "docx", "pptx"} and bool(source_file_path)

    def prepare_document_for_analysis(
        self,
        *,
        source_text: str,
        source_type: str,
        source_file_path: str | None,
        source_file_name: str | None,
    ) -> PreparedDocumentBundle:
        normalized_type = source_type.strip().lower()
        display_name = source_file_name or "document.pdf"

        if normalized_type == "pdf":
            if not source_file_path:
                raise DocumentPipelineError(
                    "PDF source file path is required for multimodal analysis."
                )
            return PreparedDocumentBundle(
                analysis_pdf_path=source_file_path,
                analysis_pdf_bytes=None,
                analysis_display_name=display_name,
                analysis_artifact_name=None,
                page_context={},
                text_artifacts={},
                metadata={
                    "normalized_document_used": False,
                    "normalized_document_source_type": normalized_type,
                },
            )

        _require_reportlab()

        if normalized_type == "docx":
            pdf_bytes, page_context = _build_docx_normalized_pdf(
                source_text=source_text,
                document_name=display_name,
            )
            return PreparedDocumentBundle(
                analysis_pdf_path=None,
                analysis_pdf_bytes=pdf_bytes,
                analysis_display_name=f"{Path(display_name).stem}.pdf",
                analysis_artifact_name="normalized.pdf",
                page_context=page_context,
                text_artifacts={
                    "normalized_page_context.json": json.dumps(
                        _serialize_page_context(page_context),
                        ensure_ascii=True,
                        indent=2,
                    ),
                },
                metadata={
                    "normalized_document_used": True,
                    "normalized_document_source_type": normalized_type,
                    "normalized_document_page_count": len(page_context),
                },
            )

        if normalized_type == "pptx":
            slides = _parse_pptx_source_text(source_text)
            if not slides:
                raise DocumentPipelineError("Could not parse slides from the extracted PPTX text.")
            pdf_bytes, page_context = _build_pptx_normalized_pdf(
                slides=slides,
                document_name=display_name,
            )
            slide_notes = [
                {
                    "slide_number": slide.slide_number,
                    "title": slide.title,
                    "notes": slide.notes_text or "",
                }
                for slide in slides
                if slide.notes_text
            ]
            text_artifacts = {
                "normalized_page_context.json": json.dumps(
                    _serialize_page_context(page_context),
                    ensure_ascii=True,
                    indent=2,
                ),
            }
            if slide_notes:
                text_artifacts["slide_notes.json"] = json.dumps(
                    slide_notes,
                    ensure_ascii=True,
                    indent=2,
                )
            return PreparedDocumentBundle(
                analysis_pdf_path=None,
                analysis_pdf_bytes=pdf_bytes,
                analysis_display_name=f"{Path(display_name).stem}.pdf",
                analysis_artifact_name="normalized.pdf",
                page_context=page_context,
                text_artifacts=text_artifacts,
                metadata={
                    "normalized_document_used": True,
                    "normalized_document_source_type": normalized_type,
                    "normalized_document_page_count": len(page_context),
                    "normalized_document_slide_count": len(slides),
                    "normalized_document_has_slide_notes": bool(slide_notes),
                },
            )

        raise DocumentPipelineError(f"Unsupported multimodal document type: {source_type}")

    def analyze_pdf_document(
        self,
        *,
        source_file_path: str,
        source_display_name: str,
        title: str | None,
        script_mode: str,
        page_context: dict[int, str] | None = None,
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
                filename=f"{Path(source_display_name).stem}_pages_{chunk.page_start:03d}_{chunk.page_end:03d}.pdf",
                title=title,
                chunk_index=chunk.index,
                chunk_count=len(chunks),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                script_mode=script_mode,
                supplemental_text=_chunk_supplemental_text(
                    page_context or {},
                    page_numbers=chunk.page_numbers,
                ),
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
        podcast_length: str,
    ) -> dict[str, object]:
        provider = self._provider_factory()
        return provider.build_podcast_plan(
            document_map=document_map,
            title=title,
            script_mode=script_mode,
            podcast_length=podcast_length,
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
            lines.append(
                f"Pages {page_start}-{page_end}: {_string_value(summary.get('summary')) or ''}".rstrip()
            )
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


def _require_reportlab() -> None:
    if canvas is None or letter is None or landscape is None or inch is None or stringWidth is None:
        raise DocumentPipelineError("Document normalization requires the `reportlab` package.")


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


def _chunk_supplemental_text(
    page_context: dict[int, str], *, page_numbers: tuple[int, ...]
) -> str | None:
    if not page_context:
        return None

    seen: set[str] = set()
    blocks: list[str] = []
    for page_number in page_numbers:
        block = (page_context.get(page_number) or "").strip()
        if not block or block in seen:
            continue
        seen.add(block)
        blocks.append(f"Page {page_number} context:\n{block}")
    if not blocks:
        return None
    return "\n\n".join(blocks)


def _serialize_page_context(page_context: dict[int, str]) -> list[dict[str, object]]:
    return [
        {"page_number": page_number, "text": text}
        for page_number, text in sorted(page_context.items())
    ]


def _build_docx_normalized_pdf(
    *, source_text: str, document_name: str
) -> tuple[bytes, dict[int, str]]:
    paragraphs = [block.strip() for block in source_text.split("\n\n") if block.strip()]
    if not paragraphs:
        raise DocumentPipelineError("No extracted DOCX text was available for PDF normalization.")

    pages, page_context = _paginate_docx_pages(
        document_title=Path(document_name).stem or "Document",
        paragraphs=paragraphs,
    )
    return _render_pdf_pages(pages, page_size=letter), page_context


def _build_pptx_normalized_pdf(
    *,
    slides: list[SlideContent],
    document_name: str,
) -> tuple[bytes, dict[int, str]]:
    document_title = Path(document_name).stem or "Presentation"
    page_size = landscape(letter)
    width, height = page_size
    margin = 0.75 * inch
    usable_width = width - (2 * margin)
    usable_height = height - (2 * margin)

    pages: list[list[RenderedLine]] = []
    page_context: dict[int, str] = {}
    current_page: list[RenderedLine] = []
    current_height = 0.0
    current_slide_context: str | None = None

    def commit_page() -> None:
        nonlocal current_page, current_height, current_slide_context
        if not current_page:
            return
        pages.append(list(current_page))
        if current_slide_context:
            page_context[len(pages)] = current_slide_context
        current_page = []
        current_height = 0.0
        current_slide_context = None

    def add_line(text: str, font_name: str, font_size: float, leading: float) -> None:
        nonlocal current_height
        current_page.append(
            RenderedLine(
                text=text,
                font_name=font_name,
                font_size=font_size,
                leading=leading,
            )
        )
        current_height += leading

    def start_slide_page(slide: SlideContent, *, continued: bool) -> None:
        nonlocal current_slide_context
        commit_page()
        title_text = slide.title or f"Slide {slide.slide_number}"
        heading = f"{document_title} - Slide {slide.slide_number}: {title_text}"
        if continued:
            heading = f"{heading} (continued)"
        current_slide_context = _slide_context_text(slide)
        for line in _wrap_text(heading, usable_width, _HEADER_FONT, _HEADER_FONT_SIZE):
            add_line(line, _HEADER_FONT, _HEADER_FONT_SIZE, _HEADER_LEADING)
        add_line("", _BODY_FONT, _BODY_FONT_SIZE, _SPACER_LEADING)

    for slide in slides:
        start_slide_page(slide, continued=False)

        body_lines = list(slide.body_lines)
        if body_lines:
            for line in _wrap_text(
                "Slide content", usable_width, _SECTION_FONT, _SECTION_FONT_SIZE
            ):
                if current_height + _SECTION_LEADING > usable_height:
                    start_slide_page(slide, continued=True)
                add_line(line, _SECTION_FONT, _SECTION_FONT_SIZE, _SECTION_LEADING)
            for body_line in body_lines:
                for wrapped in _wrap_text(
                    f"- {body_line}", usable_width, _BODY_FONT, _BODY_FONT_SIZE
                ):
                    if current_height + _BODY_LEADING > usable_height:
                        start_slide_page(slide, continued=True)
                    add_line(wrapped, _BODY_FONT, _BODY_FONT_SIZE, _BODY_LEADING)

        if slide.notes_text:
            if current_height + (_SECTION_LEADING * 2) > usable_height:
                start_slide_page(slide, continued=True)
            add_line("", _BODY_FONT, _BODY_FONT_SIZE, _SPACER_LEADING)
            for line in _wrap_text(
                "Speaker notes", usable_width, _SECTION_FONT, _SECTION_FONT_SIZE
            ):
                if current_height + _SECTION_LEADING > usable_height:
                    start_slide_page(slide, continued=True)
                add_line(line, _SECTION_FONT, _SECTION_FONT_SIZE, _SECTION_LEADING)
            for note_line in slide.notes_text.splitlines():
                if not note_line.strip():
                    continue
                for wrapped in _wrap_text(
                    note_line.strip(), usable_width, _BODY_FONT, _BODY_FONT_SIZE
                ):
                    if current_height + _BODY_LEADING > usable_height:
                        start_slide_page(slide, continued=True)
                    add_line(wrapped, _BODY_FONT, _BODY_FONT_SIZE, _BODY_LEADING)

    commit_page()
    return _render_pdf_pages(pages, page_size=page_size), page_context


def _paginate_docx_pages(
    *,
    document_title: str,
    paragraphs: list[str],
) -> tuple[list[list[RenderedLine]], dict[int, str]]:
    page_size = letter
    width, height = page_size
    margin = 0.75 * inch
    usable_width = width - (2 * margin)
    usable_height = height - (2 * margin)

    pages: list[list[RenderedLine]] = []
    page_context: dict[int, str] = {}
    current_page: list[RenderedLine] = []
    current_text_lines: list[str] = []
    current_height = 0.0
    page_number = 0

    def commit_page() -> None:
        nonlocal current_page, current_height, current_text_lines
        if not current_page:
            return
        pages.append(list(current_page))
        page_context[len(pages)] = "\n".join(
            line for line in current_text_lines if line.strip()
        ).strip()
        current_page = []
        current_text_lines = []
        current_height = 0.0

    def add_line(
        text: str,
        font_name: str,
        font_size: float,
        leading: float,
        *,
        include_in_context: bool = True,
    ) -> None:
        nonlocal current_height
        current_page.append(
            RenderedLine(
                text=text,
                font_name=font_name,
                font_size=font_size,
                leading=leading,
            )
        )
        current_height += leading
        if include_in_context and text.strip():
            current_text_lines.append(text)

    def start_page(*, continued: bool) -> None:
        nonlocal page_number
        commit_page()
        page_number += 1
        heading = f"Document: {document_title}"
        if continued:
            heading = f"{heading} (continued)"
        for line in _wrap_text(heading, usable_width, _HEADER_FONT, _HEADER_FONT_SIZE):
            add_line(
                line, _HEADER_FONT, _HEADER_FONT_SIZE, _HEADER_LEADING, include_in_context=False
            )
        add_line("", _BODY_FONT, _BODY_FONT_SIZE, _SPACER_LEADING, include_in_context=False)

    start_page(continued=False)
    for paragraph in paragraphs:
        for wrapped in _wrap_text(paragraph, usable_width, _BODY_FONT, _BODY_FONT_SIZE):
            if current_height + _BODY_LEADING > usable_height:
                start_page(continued=True)
            add_line(wrapped, _BODY_FONT, _BODY_FONT_SIZE, _BODY_LEADING)
        if current_height + _SPACER_LEADING > usable_height:
            start_page(continued=True)
        else:
            add_line("", _BODY_FONT, _BODY_FONT_SIZE, _SPACER_LEADING, include_in_context=False)

    commit_page()
    return pages, page_context


def _parse_pptx_source_text(source_text: str) -> list[SlideContent]:
    slides: list[SlideContent] = []
    current_number: int | None = None
    current_title = ""
    body_lines: list[str] = []
    notes_lines: list[str] = []
    in_notes = False

    def flush() -> None:
        nonlocal current_number, current_title, body_lines, notes_lines, in_notes
        if current_number is None:
            return
        slides.append(
            SlideContent(
                slide_number=current_number,
                title=current_title,
                body_lines=tuple(line for line in body_lines if line),
                notes_text="\n".join(line for line in notes_lines if line).strip() or None,
            )
        )
        current_number = None
        current_title = ""
        body_lines = []
        notes_lines = []
        in_notes = False

    for raw_line in source_text.splitlines():
        stripped = raw_line.strip()
        match = _SLIDE_HEADER_RE.match(stripped)
        if match:
            flush()
            current_number = int(match.group("number"))
            current_title = (match.group("title") or "").strip()
            continue
        if current_number is None:
            continue
        if stripped == "Speaker notes:":
            in_notes = True
            continue
        if not stripped:
            continue
        if in_notes:
            notes_lines.append(stripped)
        else:
            body_lines.append(stripped)

    flush()
    return slides


def _slide_context_text(slide: SlideContent) -> str:
    parts = [f"Slide {slide.slide_number}: {slide.title}".strip()]
    if slide.body_lines:
        parts.append("Slide content:")
        parts.extend(f"- {line}" for line in slide.body_lines)
    if slide.notes_text:
        parts.append("Speaker notes:")
        parts.append(slide.notes_text)
    return "\n".join(part for part in parts if part.strip()).strip()


def _render_pdf_pages(
    pages: list[list[RenderedLine]],
    *,
    page_size: tuple[float, float],
) -> bytes:
    if not pages:
        raise DocumentPipelineError("No pages were generated for PDF normalization.")

    assert canvas is not None
    assert inch is not None

    width, height = page_size
    margin = 0.75 * inch
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=page_size)

    for page in pages:
        y = height - margin
        for line in page:
            pdf.setFont(line.font_name, line.font_size)
            if line.text:
                pdf.drawString(margin, y, line.text)
            y -= line.leading
        pdf.showPage()

    pdf.save()
    return buffer.getvalue()


def _wrap_text(
    text: str,
    width: float,
    font_name: str,
    font_size: float,
) -> list[str]:
    if not text.strip():
        return [""]

    wrapped: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            wrapped.append("")
            continue

        words = stripped.split()
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if stringWidth(candidate, font_name, font_size) <= width:
                current = candidate
                continue
            wrapped.append(current)
            current = word

        if stringWidth(current, font_name, font_size) <= width:
            wrapped.append(current)
            continue

        wrapped.extend(_split_long_word(current, width, font_name, font_size))

    return wrapped or [text.strip()]


def _split_long_word(
    word: str,
    width: float,
    font_name: str,
    font_size: float,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in word:
        candidate = f"{current}{character}"
        if current and stringWidth(candidate, font_name, font_size) > width:
            chunks.append(current)
            current = character
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [word]


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
