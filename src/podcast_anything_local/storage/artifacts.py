"""Local filesystem artifact storage."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ArtifactStoreError(RuntimeError):
    """Base error for artifact storage operations."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when a requested artifact does not exist."""


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    name: str
    relative_path: str
    absolute_path: str
    size_bytes: int


class LocalArtifactStore:
    """Read and write job artifacts under a local directory."""

    def __init__(self, jobs_dir: Path) -> None:
        self._jobs_dir = jobs_dir

    def save_uploaded_file(self, job_id: str, filename: str, data: bytes) -> str:
        sanitized = Path(filename).name or "upload.bin"
        job_dir = self.ensure_job_dir(job_id)
        stored_path = job_dir / f"input_{sanitized}"
        stored_path.write_bytes(data)
        return str(stored_path)

    def write_text(self, job_id: str, filename: str, text: str) -> str:
        path = self.ensure_job_dir(job_id) / filename
        path.write_text(_sanitize_text_for_utf8(text), encoding="utf-8")
        return str(path)

    def write_bytes(self, job_id: str, filename: str, data: bytes) -> str:
        path = self.ensure_job_dir(job_id) / filename
        path.write_bytes(data)
        return str(path)

    def read_text(self, absolute_path: str) -> str:
        return Path(absolute_path).read_text(encoding="utf-8")

    def delete_artifact(self, absolute_path: str) -> None:
        artifact_path = Path(absolute_path).resolve()
        jobs_dir = self._jobs_dir.resolve()
        if jobs_dir not in artifact_path.parents:
            raise ArtifactNotFoundError(f"Artifact not found: {absolute_path}")
        if artifact_path.is_file():
            os.remove(artifact_path)

    def ensure_job_dir(self, job_id: str) -> Path:
        job_dir = self._jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def get_artifact(self, job_id: str, artifact_name: str) -> ArtifactInfo:
        sanitized_name = Path(artifact_name).name
        if sanitized_name != artifact_name or sanitized_name in {"", ".", ".."}:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_name}")

        artifact_path = (self.ensure_job_dir(job_id) / sanitized_name).resolve()
        job_dir = self.ensure_job_dir(job_id).resolve()
        if job_dir not in artifact_path.parents:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_name}")
        if not artifact_path.is_file():
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_name}")

        return ArtifactInfo(
            name=artifact_path.name,
            relative_path=str(artifact_path.relative_to(self._jobs_dir.parent)),
            absolute_path=str(artifact_path),
            size_bytes=artifact_path.stat().st_size,
        )

    def list_artifacts(self, job_id: str) -> list[ArtifactInfo]:
        job_dir = self.ensure_job_dir(job_id)
        artifacts: list[ArtifactInfo] = []
        for path in sorted(job_dir.iterdir()):
            if not path.is_file():
                continue
            artifacts.append(
                ArtifactInfo(
                    name=path.name,
                    relative_path=str(path.relative_to(self._jobs_dir.parent)),
                    absolute_path=str(path.resolve()),
                    size_bytes=path.stat().st_size,
                )
            )
        return artifacts


def _sanitize_text_for_utf8(text: str) -> str:
    return "".join(
        character if not _is_surrogate_codepoint(character) else "\ufffd" for character in text
    )


def _is_surrogate_codepoint(character: str) -> bool:
    codepoint = ord(character)
    return 0xD800 <= codepoint <= 0xDFFF
