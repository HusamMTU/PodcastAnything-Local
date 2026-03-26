"""FastAPI routes for job operations."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from podcast_anything_local.db.models import CreateJobInput
from podcast_anything_local.db.repository import JobNotFoundError, generate_job_id
from podcast_anything_local.jobs.audio_streams import JobAudioStreamNotFoundError
from podcast_anything_local.providers.rewrite.prompting import SUPPORTED_PODCAST_LENGTHS
from podcast_anything_local.schemas.config import AppConfigResponse
from podcast_anything_local.schemas.jobs import ArtifactResponse, CreateJobRequest, JobResponse
from podcast_anything_local.storage.artifacts import ArtifactNotFoundError

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config", response_model=AppConfigResponse)
def app_config(request: Request) -> AppConfigResponse:
    settings = request.app.state.settings
    return AppConfigResponse(
        app_name=settings.app_name,
        default_web_extractor=settings.web_extractor,
        script_writer="openai",
        default_tts_provider=settings.tts_provider,
        default_podcast_length=settings.podcast_length_default,
        default_style=settings.rewrite_style,
        supported_web_extractors=["auto", "trafilatura", "bs4"],
        supported_tts_providers=["openai", "elevenlabs"],
        supported_podcast_lengths=list(SUPPORTED_PODCAST_LENGTHS),
    )


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(request: Request) -> JobResponse:
    repository = request.app.state.repository
    artifact_store = request.app.state.artifact_store
    executor = request.app.state.executor
    settings = request.app.state.settings

    try:
        payload = await _parse_create_request(
            request,
            default_podcast_length=settings.podcast_length_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = generate_job_id()
    source_file_path: str | None = None
    metadata: dict[str, Any] = {}

    if payload["source_file"] is not None:
        upload = payload["source_file"]
        file_bytes = await upload.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        source_file_path = artifact_store.save_uploaded_file(job_id, upload.filename or "upload.bin", file_bytes)
        metadata["uploaded_content_type"] = upload.content_type
    elif payload["source_text"] is not None:
        source_text = payload["source_text"]
        source_file_name = payload["source_file_name"] or "pasted_text.txt"
        source_file_path = artifact_store.save_uploaded_file(
            job_id,
            source_file_name,
            source_text.encode("utf-8"),
        )
        metadata["submitted_text_char_count"] = len(source_text)

    record = repository.create_job(
        CreateJobInput(
            job_id=job_id,
            source_kind=payload["source_kind"],
            source_url=payload["source_url"],
            source_file_name=payload["source_file_name"],
            source_file_path=source_file_path,
            title=payload["title"],
            style=payload["style"] or settings.rewrite_style,
            script_mode=payload["script_mode"],
            podcast_length=payload["podcast_length"],
            tts_provider=payload["tts_provider"] or settings.tts_provider,
            voice_id=payload["voice_id"],
            voice_id_b=payload["voice_id_b"],
            metadata=metadata,
        )
    )
    executor.submit(record.job_id)
    return JobResponse.from_record(record)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(request: Request) -> list[JobResponse]:
    repository = request.app.state.repository
    return [JobResponse.from_record(job) for job in repository.list_jobs()]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request) -> JobResponse:
    repository = request.app.state.repository
    try:
        job = repository.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JobResponse.from_record(job)


@router.get("/jobs/{job_id}/artifacts", response_model=list[ArtifactResponse])
def get_job_artifacts(job_id: str, request: Request) -> list[ArtifactResponse]:
    repository = request.app.state.repository
    artifact_store = request.app.state.artifact_store
    try:
        repository.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        ArtifactResponse.from_info(item, job_id=job_id)
        for item in artifact_store.list_artifacts(job_id)
    ]


@router.get("/jobs/{job_id}/artifacts/{artifact_name}")
def download_job_artifact(job_id: str, artifact_name: str, request: Request) -> FileResponse:
    repository = request.app.state.repository
    artifact_store = request.app.state.artifact_store
    try:
        repository.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        artifact = artifact_store.get_artifact(job_id, artifact_name)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type, _ = mimetypes.guess_type(artifact.name)
    return FileResponse(
        path=artifact.absolute_path,
        media_type=media_type or "application/octet-stream",
        filename=artifact.name,
    )


@router.get("/jobs/{job_id}/audio-stream", response_model=None)
def stream_job_audio(job_id: str, request: Request) -> StreamingResponse | FileResponse:
    repository = request.app.state.repository
    artifact_store = request.app.state.artifact_store
    audio_stream_broker = request.app.state.audio_stream_broker
    try:
        job = repository.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return StreamingResponse(
            audio_stream_broker.iter_chunks(job_id),
            media_type=audio_stream_broker.get_content_type(job_id),
            headers={"Cache-Control": "no-store"},
        )
    except JobAudioStreamNotFoundError:
        if not job.audio_artifact:
            raise HTTPException(
                status_code=404,
                detail=f"Live audio stream not available for job: {job_id}",
            ) from None

    try:
        artifact = artifact_store.get_artifact(job_id, Path(job.audio_artifact).name)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type, _ = mimetypes.guess_type(artifact.name)
    return FileResponse(
        path=artifact.absolute_path,
        media_type=media_type or "application/octet-stream",
        filename=artifact.name,
    )


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str, request: Request) -> JobResponse:
    repository = request.app.state.repository
    artifact_store = request.app.state.artifact_store
    audio_stream_broker = request.app.state.audio_stream_broker
    executor = request.app.state.executor
    try:
        existing = repository.get_job(job_id)
        audio_stream_broker.clear(job_id)
        for artifact in artifact_store.list_artifacts(job_id):
            if existing.source_file_path and artifact.absolute_path == existing.source_file_path:
                continue
            artifact_store.delete_artifact(artifact.absolute_path)
        record = repository.reset_for_retry(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArtifactNotFoundError:
        record = repository.reset_for_retry(job_id)
    executor.submit(job_id)
    return JobResponse.from_record(record)


async def _parse_create_request(
    request: Request,
    *,
    default_podcast_length: str,
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_payload = await request.json()
        if "podcast_length" not in raw_payload:
            raw_payload["podcast_length"] = default_podcast_length
        payload = CreateJobRequest.model_validate(raw_payload)
        return _normalize_inputs(
            source_url=payload.source_url,
            source_text=payload.source_text,
            source_file=None,
            title=payload.title,
            style=payload.style,
            script_mode=payload.script_mode,
            podcast_length=payload.podcast_length,
            tts_provider=payload.tts_provider,
            voice_id=payload.voice_id,
            voice_id_b=payload.voice_id_b,
        )

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        upload = form.get("source_file")
        source_file = upload if _is_upload_file(upload) else None
        return _normalize_inputs(
            source_url=_optional_form_value(form.get("source_url")),
            source_text=_optional_form_value(form.get("source_text")),
            source_file=source_file,
            title=_optional_form_value(form.get("title")),
            style=_optional_form_value(form.get("style")) or "podcast",
            script_mode=_optional_form_value(form.get("script_mode")) or "single",
            podcast_length=_optional_form_value(form.get("podcast_length")) or default_podcast_length,
            tts_provider=_optional_form_value(form.get("tts_provider")),
            voice_id=_optional_form_value(form.get("voice_id")),
            voice_id_b=_optional_form_value(form.get("voice_id_b")),
        )

    raise ValueError("Unsupported content type. Use application/json or multipart/form-data.")


def _normalize_inputs(
    *,
    source_url: str | None,
    source_text: str | None,
    source_file: UploadFile | None,
    title: str | None,
    style: str,
    script_mode: str,
    podcast_length: str,
    tts_provider: str | None,
    voice_id: str | None,
    voice_id_b: str | None,
) -> dict[str, Any]:
    input_count = int(bool(source_url)) + int(bool(source_text)) + int(bool(source_file))
    if input_count != 1:
        raise ValueError("Provide exactly one of source_url, source_text, or source_file.")
    if script_mode not in {"single", "duo"}:
        raise ValueError("script_mode must be one of: single, duo")
    if podcast_length not in set(SUPPORTED_PODCAST_LENGTHS):
        supported = ", ".join(SUPPORTED_PODCAST_LENGTHS)
        raise ValueError(f"podcast_length must be one of: {supported}")
    return {
        "source_kind": "url" if source_url else ("text" if source_text else "file"),
        "source_url": source_url,
        "source_text": source_text,
        "source_file": source_file,
        "source_file_name": "pasted_text.txt" if source_text else (source_file.filename if source_file else None),
        "title": title,
        "style": style.strip() if style else "podcast",
        "script_mode": script_mode,
        "podcast_length": podcast_length,
        "tts_provider": tts_provider.strip().lower() if tts_provider else None,
        "voice_id": voice_id,
        "voice_id_b": voice_id_b,
    }


def _optional_form_value(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _is_upload_file(value: object) -> bool:
    return isinstance(value, UploadFile) or (
        hasattr(value, "filename") and hasattr(value, "read")
    )
