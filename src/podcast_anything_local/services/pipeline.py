"""End-to-end pipeline orchestration for one job."""

from __future__ import annotations

import json

from podcast_anything_local.db.repository import JobRepository
from podcast_anything_local.jobs.events import JobEventBroker
from podcast_anything_local.services.audio import AudioService
from podcast_anything_local.services.document_pipeline import MultimodalDocumentService
from podcast_anything_local.services.ingestion import IngestionService
from podcast_anything_local.services.rewrite import RewriteService
from podcast_anything_local.storage.artifacts import LocalArtifactStore


class PipelineService:
    def __init__(
        self,
        *,
        repository: JobRepository,
        artifact_store: LocalArtifactStore,
        ingestion_service: IngestionService,
        rewrite_service: RewriteService,
        document_service: MultimodalDocumentService,
        audio_service: AudioService,
        job_event_broker: JobEventBroker,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._ingestion_service = ingestion_service
        self._rewrite_service = rewrite_service
        self._document_service = document_service
        self._audio_service = audio_service
        self._job_event_broker = job_event_broker

    def run_job(self, job_id: str) -> None:
        stage = "ingesting"
        try:
            job = self._repository.mark_running(job_id, stage=stage)
            source_text, ingestion_metadata = self._ingestion_service.ingest(
                source_kind=job.source_kind,
                source_url=job.source_url,
                source_file_path=job.source_file_path,
                source_file_name=job.source_file_name,
            )
            source_path = self._artifact_store.write_text(job_id, "source.txt", source_text)
            self._repository.record_artifact(
                job_id,
                source_artifact=source_path,
                metadata_updates=ingestion_metadata,
            )

            stage = "rewriting"
            job = self._repository.get_job(job_id)
            source_type = str(ingestion_metadata.get("source_type") or "")
            multimodal_pdf = self._document_service.should_use(
                source_type=source_type,
                source_file_path=job.source_file_path,
                rewrite_provider=job.rewrite_provider,
            )
            if source_type == "pdf" and not source_text.strip() and not multimodal_pdf:
                raise RuntimeError(
                    "This PDF does not contain extractable text. Use the OpenAI rewrite provider "
                    "for multimodal PDF analysis."
                )
            if multimodal_pdf:
                stage = "analyzing"
                self._repository.update_stage(job_id, stage)
                analysis = self._document_service.analyze_pdf_document(
                    source_file_path=job.source_file_path or "",
                    title=job.title,
                    script_mode=job.script_mode,
                    rewrite_provider=job.rewrite_provider,
                )
                for filename, content in self._document_service.build_artifacts(
                    analysis=analysis,
                ).items():
                    self._artifact_store.write_text(job_id, filename, content)
                self._repository.record_artifact(
                    job_id,
                    metadata_updates=self._document_service.build_metadata(analysis=analysis),
                )

                stage = "planning"
                self._repository.update_stage(job_id, stage)
                podcast_plan = self._document_service.build_podcast_plan(
                    document_map=analysis.document_map,
                    title=job.title,
                    script_mode=job.script_mode,
                    rewrite_provider=job.rewrite_provider,
                )
                rewrite_source_text = self._document_service.build_rewrite_source_text(
                    analysis=analysis,
                    podcast_plan=podcast_plan,
                )
                plan_artifacts = self._document_service.build_plan_artifacts(
                    podcast_plan=podcast_plan,
                    rewrite_source_text=rewrite_source_text,
                )
                rewrite_input_path = ""
                for filename, content in plan_artifacts.items():
                    written_path = self._artifact_store.write_text(job_id, filename, content)
                    if filename == "rewrite_input.txt":
                        rewrite_input_path = written_path
                self._repository.record_artifact(
                    job_id,
                    metadata_updates={
                        "rewrite_input_char_count": len(rewrite_source_text),
                        "rewrite_input_truncated": False,
                        "rewrite_input_artifact": rewrite_input_path,
                    },
                )
                effective_title = job.title
                working_title = podcast_plan.get("working_title")
                if not effective_title and isinstance(working_title, str) and working_title.strip():
                    effective_title = working_title.strip()
            else:
                stage = "rewriting"
                self._repository.update_stage(job_id, stage)
                rewrite_source_text, rewrite_metadata = self._rewrite_service.prepare_source_text(
                    source_text=source_text,
                    script_mode=job.script_mode,
                )
                self._repository.record_artifact(
                    job_id,
                    metadata_updates=rewrite_metadata,
                )
                effective_title = job.title

            stage = "rewriting"
            self._repository.update_stage(job_id, stage)
            script_text = self._rewrite_service.rewrite(
                source_text=rewrite_source_text,
                title=effective_title,
                style=job.style,
                source_type=source_type,
                script_mode=job.script_mode,
                provider_name=job.rewrite_provider,
                on_chunk=lambda chunk: self._job_event_broker.publish_rewrite_chunk(job_id, chunk),
            )
            generated_title = job.title
            title_metadata: dict[str, object] = {}
            if not generated_title:
                try:
                    generated_title = self._rewrite_service.generate_title(
                        script_text=script_text,
                        source_type=str(job.metadata.get("source_type") or ""),
                        script_mode=job.script_mode,
                        provider_name=job.rewrite_provider,
                    )
                    title_metadata["title_source"] = "llm"
                except Exception as exc:
                    title_metadata["title_generation_error"] = str(exc)
            self._job_event_broker.publish_rewrite_complete(job_id)
            script_path = self._artifact_store.write_text(job_id, "script.txt", script_text)
            self._repository.record_artifact(
                job_id,
                script_artifact=script_path,
                title=generated_title,
                metadata_updates={
                    "script_char_count": len(script_text),
                    **title_metadata,
                },
            )

            stage = "synthesizing"
            self._repository.update_stage(job_id, stage)
            job = self._repository.get_job(job_id)
            audio = self._audio_service.synthesize(
                script_text=script_text,
                script_mode=job.script_mode,
                provider_name=job.tts_provider,
                voice_id=job.voice_id,
                voice_id_b=job.voice_id_b,
            )
            audio_path = self._artifact_store.write_bytes(job_id, audio.file_name, audio.data)
            final_job = self._repository.record_artifact(
                job_id,
                audio_artifact=audio_path,
                metadata_updates={
                    "audio_content_type": audio.content_type,
                    "audio_file_name": audio.file_name,
                },
            )

            metadata_path = self._artifact_store.write_text(
                job_id,
                "metadata.json",
                json.dumps(
                    {
                        "job_id": final_job.job_id,
                        "status": "completed",
                        "source_kind": final_job.source_kind,
                        "source_url": final_job.source_url,
                        "source_file_name": final_job.source_file_name,
                        "title": final_job.title,
                        "style": final_job.style,
                        "script_mode": final_job.script_mode,
                        "rewrite_provider": final_job.rewrite_provider,
                        "tts_provider": final_job.tts_provider,
                        "metadata": final_job.metadata,
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
            )
            self._repository.record_artifact(
                job_id,
                metadata_updates={"metadata_artifact": metadata_path},
            )
            self._repository.mark_completed(job_id)
        except Exception as exc:
            self._job_event_broker.publish_job_failed(job_id, str(exc))
            self._repository.mark_failed(job_id, str(exc), stage)
            raise
