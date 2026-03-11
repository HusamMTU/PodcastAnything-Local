"""End-to-end pipeline orchestration for one job."""

from __future__ import annotations

import json

from podcast_anything_local.db.repository import JobRepository
from podcast_anything_local.jobs.events import JobEventBroker
from podcast_anything_local.services.audio import AudioService
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
        audio_service: AudioService,
        job_event_broker: JobEventBroker,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._ingestion_service = ingestion_service
        self._rewrite_service = rewrite_service
        self._audio_service = audio_service
        self._job_event_broker = job_event_broker

    def run_job(self, job_id: str) -> None:
        stage = "ingesting"
        try:
            job = self._repository.mark_running(job_id, stage=stage)
            source_text, ingestion_metadata = self._ingestion_service.ingest(
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
            self._repository.update_stage(job_id, stage)
            job = self._repository.get_job(job_id)
            rewrite_source_text, rewrite_metadata = self._rewrite_service.prepare_source_text(
                source_text=source_text,
                script_mode=job.script_mode,
            )
            self._repository.record_artifact(
                job_id,
                metadata_updates=rewrite_metadata,
            )
            script_text = self._rewrite_service.rewrite(
                source_text=rewrite_source_text,
                title=job.title,
                style=job.style,
                source_type=str(job.metadata.get("source_type") or ""),
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
