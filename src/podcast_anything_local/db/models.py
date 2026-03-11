"""Dataclasses shared by the repository and API layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CreateJobInput:
    source_kind: str
    job_id: str | None = None
    source_url: str | None = None
    source_file_name: str | None = None
    source_file_path: str | None = None
    title: str | None = None
    style: str = "podcast"
    script_mode: str = "single"
    rewrite_provider: str = "demo"
    tts_provider: str = "wave"
    voice_id: str | None = None
    voice_id_b: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JobRecord:
    job_id: str
    status: str
    current_stage: str | None
    source_kind: str
    source_url: str | None
    source_file_name: str | None
    source_file_path: str | None
    title: str | None
    style: str
    script_mode: str
    rewrite_provider: str
    tts_provider: str
    voice_id: str | None
    voice_id_b: str | None
    source_artifact: str | None
    script_artifact: str | None
    audio_artifact: str | None
    error: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
