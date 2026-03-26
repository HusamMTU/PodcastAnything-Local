"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from podcast_anything_local.api.routes import router
from podcast_anything_local.core.config import Settings, load_settings
from podcast_anything_local.db.repository import JobRepository
from podcast_anything_local.jobs.audio_streams import JobAudioStreamBroker
from podcast_anything_local.jobs.executor import JobExecutor
from podcast_anything_local.services.audio import AudioService
from podcast_anything_local.services.document_pipeline import MultimodalDocumentService
from podcast_anything_local.services.ingestion import IngestionService
from podcast_anything_local.services.pipeline import PipelineService
from podcast_anything_local.services.rewrite import RewriteService
from podcast_anything_local.storage.artifacts import LocalArtifactStore
from podcast_anything_local.web import mount_web_ui


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ensure_directories()
        repository = JobRepository(resolved_settings.database_path)
        repository.init_db()
        artifact_store = LocalArtifactStore(resolved_settings.jobs_dir)
        ingestion_service = IngestionService(web_extractor=resolved_settings.web_extractor)
        rewrite_service = RewriteService(resolved_settings)
        document_service = MultimodalDocumentService(resolved_settings)
        audio_service = AudioService(resolved_settings)
        audio_stream_broker = JobAudioStreamBroker()
        pipeline_service = PipelineService(
            repository=repository,
            artifact_store=artifact_store,
            ingestion_service=ingestion_service,
            rewrite_service=rewrite_service,
            document_service=document_service,
            audio_service=audio_service,
            audio_stream_broker=audio_stream_broker,
        )
        executor = JobExecutor(repository=repository, pipeline_service=pipeline_service)

        app.state.settings = resolved_settings
        app.state.repository = repository
        app.state.artifact_store = artifact_store
        app.state.audio_stream_broker = audio_stream_broker
        app.state.executor = executor

        executor.start()
        try:
            yield
        finally:
            executor.stop()

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    app.include_router(router)
    mount_web_ui(app)
    return app


app = create_app()
