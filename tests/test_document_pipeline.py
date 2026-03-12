from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from podcast_anything_local.core.config import Settings
from podcast_anything_local.services.document_pipeline import MultimodalDocumentService


class _FakeDocumentProvider:
    def __init__(self) -> None:
        self.chunk_calls: list[tuple[int, int, int]] = []
        self.map_calls: int = 0
        self.plan_calls: int = 0

    def summarize_pdf_chunk(
        self,
        *,
        pdf_bytes: bytes,
        filename: str,
        title: str | None,
        chunk_index: int,
        chunk_count: int,
        page_start: int,
        page_end: int,
        script_mode: str,
    ) -> dict[str, object]:
        self.chunk_calls.append((chunk_index, page_start, page_end))
        return {
            "page_start": page_start,
            "page_end": page_end,
            "summary": f"Summary for pages {page_start}-{page_end}",
            "key_points": [f"Point {chunk_index}"],
            "visual_elements": [f"Visual {chunk_index}"],
            "podcast_angles": [f"Angle {chunk_index}"],
            "must_include_details": [f"Detail {chunk_index}"],
            "caveats": [],
        }

    def build_document_map(
        self,
        *,
        chunk_summaries: list[dict[str, object]],
        title: str | None,
        script_mode: str,
    ) -> dict[str, object]:
        self.map_calls += 1
        return {
            "overall_summary": "Combined summary",
            "narrative_arc": ["Start", "Middle", "End"],
            "must_include": ["Key fact"],
            "supporting_details": ["Supporting detail"],
            "visual_takeaways": ["Important chart"],
            "caveats": [],
        }

    def build_podcast_plan(
        self,
        *,
        document_map: dict[str, object],
        title: str | None,
        script_mode: str,
    ) -> dict[str, object]:
        self.plan_calls += 1
        return {
            "working_title": "Quantum Document Brief",
            "audience": "General technical audience",
            "angle": "Explain the big picture clearly",
            "intro": "Set up the topic fast.",
            "outro": "Close with one takeaway.",
            "must_include": ["Key fact"],
            "segments": [
                {
                    "name": "Foundations",
                    "purpose": "Explain the core idea",
                    "beats": ["Beat A", "Beat B"],
                    "source_pages": [1, 2],
                }
            ],
        }


def _build_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        app_env="test",
        app_name="Podcast Anything Local Test",
        data_dir=data_dir,
        database_path=data_dir / "app.db",
        jobs_dir=data_dir / "jobs",
        web_extractor="auto",
        rewrite_style="podcast",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        tts_provider="piper",
        tts_default_voice=None,
        tts_duo_voice=None,
        piper_model_path=None,
        piper_model_path_b=None,
        piper_config_path=None,
        piper_config_path_b=None,
        piper_speaker_id=None,
        piper_speaker_id_b=None,
        elevenlabs_api_key=None,
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_output_format="mp3_44100_128",
    )


def test_multimodal_document_service_builds_chunks_and_plan(tmp_path: Path) -> None:
    pdf_path = tmp_path / "document.pdf"
    writer = PdfWriter()
    for _ in range(7):
        writer.add_blank_page(width=300, height=300)
    with pdf_path.open("wb") as file:
        writer.write(file)

    fake_provider = _FakeDocumentProvider()
    service = MultimodalDocumentService(
        _build_settings(tmp_path),
        provider_factory=lambda: fake_provider,
    )

    assert service.should_use(
        source_type="pdf",
        source_file_path=str(pdf_path),
    )

    analysis = service.analyze_pdf_document(
        source_file_path=str(pdf_path),
        title="Quantum Notes",
        script_mode="single",
    )
    assert analysis.page_count == 7
    assert fake_provider.chunk_calls == [(1, 1, 6), (2, 6, 7)]
    assert fake_provider.map_calls == 1

    podcast_plan = service.build_podcast_plan(
        document_map=analysis.document_map,
        title="Quantum Notes",
        script_mode="single",
    )
    rewrite_source = service.build_rewrite_source_text(
        analysis=analysis,
        podcast_plan=podcast_plan,
    )
    artifacts = service.build_artifacts(analysis=analysis)
    plan_artifacts = service.build_plan_artifacts(
        podcast_plan=podcast_plan,
        rewrite_source_text=rewrite_source,
    )

    assert fake_provider.plan_calls == 1
    assert "Quantum Document Brief" in rewrite_source
    assert "Chunk evidence:" in rewrite_source
    assert "page_index.json" in artifacts
    assert "document_map.json" in artifacts
    assert "chunk_001_summary.json" in artifacts
    assert "podcast_plan.json" in plan_artifacts
    assert "rewrite_input.txt" in plan_artifacts
