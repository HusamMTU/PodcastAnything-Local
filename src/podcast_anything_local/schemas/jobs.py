"""API schemas for jobs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from podcast_anything_local.db.models import JobRecord
from podcast_anything_local.storage.artifacts import ArtifactInfo


class CreateJobRequest(BaseModel):
    source_url: str | None = None
    source_text: str | None = None
    title: str | None = None
    style: str = "podcast"
    script_mode: Literal["single", "duo"] = "single"
    podcast_length: Literal["short", "medium", "long"] = "medium"
    tts_provider: str | None = None
    voice_id: str | None = None
    voice_id_b: str | None = None


class ArtifactResponse(BaseModel):
    name: str
    relative_path: str
    absolute_path: str
    size_bytes: int
    download_path: str

    @classmethod
    def from_info(cls, info: ArtifactInfo, *, job_id: str) -> "ArtifactResponse":
        return cls(
            name=info.name,
            relative_path=info.relative_path,
            absolute_path=info.absolute_path,
            size_bytes=info.size_bytes,
            download_path=f"/jobs/{job_id}/artifacts/{info.name}",
        )


class JobResponse(BaseModel):
    job_id: str
    status: str
    current_stage: str | None
    source_kind: str
    source_url: str | None
    source_file_name: str | None
    title: str | None
    style: str
    script_mode: str
    podcast_length: str
    tts_provider: str
    voice_id: str | None
    voice_id_b: str | None
    source_artifact: str | None
    script_artifact: str | None
    audio_artifact: str | None
    error: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_record(cls, record: JobRecord) -> "JobResponse":
        return cls(
            job_id=record.job_id,
            status=record.status,
            current_stage=record.current_stage,
            source_kind=record.source_kind,
            source_url=record.source_url,
            source_file_name=record.source_file_name,
            title=record.title,
            style=record.style,
            script_mode=record.script_mode,
            podcast_length=record.podcast_length,
            tts_provider=record.tts_provider,
            voice_id=record.voice_id,
            voice_id_b=record.voice_id_b,
            source_artifact=record.source_artifact,
            script_artifact=record.script_artifact,
            audio_artifact=record.audio_artifact,
            error=record.error,
            metadata=record.metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )
