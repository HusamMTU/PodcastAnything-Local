"""SQLite-backed job repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from podcast_anything_local.db.models import CreateJobInput, JobRecord


class JobRepositoryError(RuntimeError):
    """Raised for repository-level failures."""


class JobNotFoundError(JobRepositoryError):
    """Raised when a job does not exist."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_job_id() -> str:
    return f"job-{uuid.uuid4().hex[:12]}"


class JobRepository:
    """Persist jobs and pipeline state in SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def init_db(self) -> None:
        with self._connect() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if not columns:
                self._create_jobs_table(connection)
            elif "rewrite_provider" in columns:
                self._migrate_drop_rewrite_provider(connection)

    def create_job(self, payload: CreateJobInput) -> JobRecord:
        job_id = payload.job_id or generate_job_id()
        now = _utc_now()
        metadata_json = json.dumps(payload.metadata, ensure_ascii=True, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, status, current_stage, source_kind, source_url,
                    source_file_name, source_file_path, title, style, script_mode,
                    tts_provider, voice_id, voice_id_b,
                    source_artifact, script_artifact, audio_artifact, error,
                    metadata_json, created_at, updated_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "queued",
                    None,
                    payload.source_kind,
                    payload.source_url,
                    payload.source_file_name,
                    payload.source_file_path,
                    payload.title,
                    payload.style,
                    payload.script_mode,
                    payload.tts_provider,
                    payload.voice_id,
                    payload.voice_id_b,
                    None,
                    None,
                    None,
                    None,
                    metadata_json,
                    now,
                    now,
                    None,
                    None,
                ),
            )
        return self.get_job(job_id)

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_job(self, job_id: str) -> JobRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise JobNotFoundError(f"Job not found: {job_id}")
        return self._row_to_record(row)

    def mark_running(self, job_id: str, stage: str) -> JobRecord:
        now = _utc_now()
        self._update_fields(
            job_id,
            {
                "status": "running",
                "current_stage": stage,
                "started_at": now,
                "error": None,
                "updated_at": now,
            },
        )
        return self.get_job(job_id)

    def update_stage(self, job_id: str, stage: str) -> JobRecord:
        self._update_fields(job_id, {"current_stage": stage, "updated_at": _utc_now()})
        return self.get_job(job_id)

    def record_artifact(
        self,
        job_id: str,
        *,
        source_artifact: str | None = None,
        script_artifact: str | None = None,
        audio_artifact: str | None = None,
        title: str | None = None,
        metadata_updates: dict[str, object] | None = None,
    ) -> JobRecord:
        current = self.get_job(job_id)
        merged_metadata = dict(current.metadata)
        if metadata_updates:
            merged_metadata.update(metadata_updates)

        fields: dict[str, object | None] = {
            "updated_at": _utc_now(),
            "metadata_json": json.dumps(merged_metadata, ensure_ascii=True, sort_keys=True),
        }
        if source_artifact is not None:
            fields["source_artifact"] = source_artifact
        if script_artifact is not None:
            fields["script_artifact"] = script_artifact
        if audio_artifact is not None:
            fields["audio_artifact"] = audio_artifact
        if title is not None:
            fields["title"] = title

        self._update_fields(job_id, fields)
        return self.get_job(job_id)

    def mark_completed(self, job_id: str) -> JobRecord:
        now = _utc_now()
        self._update_fields(
            job_id,
            {
                "status": "completed",
                "current_stage": "completed",
                "completed_at": now,
                "updated_at": now,
            },
        )
        return self.get_job(job_id)

    def mark_failed(self, job_id: str, error: str, stage: str | None) -> JobRecord:
        self._update_fields(
            job_id,
            {
                "status": "failed",
                "current_stage": stage,
                "error": error,
                "updated_at": _utc_now(),
            },
        )
        return self.get_job(job_id)

    def reset_for_retry(self, job_id: str) -> JobRecord:
        current = self.get_job(job_id)
        metadata = dict(current.metadata)
        retry_count = int(metadata.get("retry_count", 0)) + 1
        metadata = {
            key: value
            for key, value in metadata.items()
            if key
            not in {
                "audio_content_type",
                "audio_file_name",
                "metadata_artifact",
                "script_char_count",
                "source_char_count",
                "source_type",
                "title_generation_error",
                "title_source",
                "multimodal_document_pipeline",
                "multimodal_document_page_count",
                "multimodal_document_chunk_count",
                "multimodal_document_chunk_pages",
                "multimodal_document_chunk_overlap_pages",
                "normalized_document_used",
                "normalized_document_source_type",
                "normalized_document_page_count",
                "normalized_document_slide_count",
                "normalized_document_has_slide_notes",
                "normalized_document_artifact",
                "normalized_page_context_artifact",
                "slide_notes_artifact",
                "rewrite_input_char_count",
                "rewrite_input_truncated",
                "rewrite_input_artifact",
            }
        }
        metadata["retry_count"] = retry_count
        reset_title = None if current.metadata.get("title_source") == "llm" else current.title
        self._update_fields(
            job_id,
            {
                "status": "queued",
                "current_stage": None,
                "title": reset_title,
                "source_artifact": None,
                "script_artifact": None,
                "audio_artifact": None,
                "error": None,
                "started_at": None,
                "completed_at": None,
                "metadata_json": json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                "updated_at": _utc_now(),
            },
        )
        return self.get_job(job_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_jobs_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                current_stage TEXT,
                source_kind TEXT NOT NULL,
                source_url TEXT,
                source_file_name TEXT,
                source_file_path TEXT,
                title TEXT,
                style TEXT NOT NULL,
                script_mode TEXT NOT NULL,
                tts_provider TEXT NOT NULL,
                voice_id TEXT,
                voice_id_b TEXT,
                source_artifact TEXT,
                script_artifact TEXT,
                audio_artifact TEXT,
                error TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
            """
        )

    def _migrate_drop_rewrite_provider(self, connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE jobs RENAME TO jobs_legacy_rewrite_provider")
        self._create_jobs_table(connection)
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, status, current_stage, source_kind, source_url,
                source_file_name, source_file_path, title, style, script_mode,
                tts_provider, voice_id, voice_id_b, source_artifact,
                script_artifact, audio_artifact, error, metadata_json,
                created_at, updated_at, started_at, completed_at
            )
            SELECT
                job_id, status, current_stage, source_kind, source_url,
                source_file_name, source_file_path, title, style, script_mode,
                tts_provider, voice_id, voice_id_b, source_artifact,
                script_artifact, audio_artifact, error, metadata_json,
                created_at, updated_at, started_at, completed_at
            FROM jobs_legacy_rewrite_provider
            """
        )
        connection.execute("DROP TABLE jobs_legacy_rewrite_provider")

    def _update_fields(self, job_id: str, updates: dict[str, object | None]) -> None:
        if not updates:
            return
        assignments = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values())
        values.append(job_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id = ?",
                values,
            )
        if cursor.rowcount == 0:
            raise JobNotFoundError(f"Job not found: {job_id}")

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            status=row["status"],
            current_stage=row["current_stage"],
            source_kind=row["source_kind"],
            source_url=row["source_url"],
            source_file_name=row["source_file_name"],
            source_file_path=row["source_file_path"],
            title=row["title"],
            style=row["style"],
            script_mode=row["script_mode"],
            tts_provider=row["tts_provider"],
            voice_id=row["voice_id"],
            voice_id_b=row["voice_id_b"],
            source_artifact=row["source_artifact"],
            script_artifact=row["script_artifact"],
            audio_artifact=row["audio_artifact"],
            error=row["error"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
