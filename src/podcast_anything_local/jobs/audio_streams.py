"""In-memory live audio stream broker for active jobs."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Iterator


class JobAudioStreamError(RuntimeError):
    """Base error for live audio stream operations."""


class JobAudioStreamNotFoundError(JobAudioStreamError):
    """Raised when no live audio stream exists for a job."""


@dataclass(slots=True)
class _StreamState:
    content_type: str
    file_name: str
    chunks: list[bytes] = field(default_factory=list)
    closed: bool = False
    error: str | None = None
    condition: threading.Condition = field(default_factory=threading.Condition)


class JobAudioStreamBroker:
    """Store and fan out live audio chunks to HTTP clients."""

    def __init__(self) -> None:
        self._streams: dict[str, _StreamState] = {}
        self._lock = threading.Lock()

    def open(self, job_id: str, *, content_type: str, file_name: str) -> None:
        state = _StreamState(content_type=content_type, file_name=file_name)
        with self._lock:
            self._streams[job_id] = state

    def publish(self, job_id: str, chunk: bytes) -> None:
        if not chunk:
            return
        state = self._require(job_id)
        with state.condition:
            state.chunks.append(chunk)
            state.condition.notify_all()

    def close(self, job_id: str) -> None:
        state = self._require(job_id)
        with state.condition:
            state.closed = True
            state.condition.notify_all()

    def fail(self, job_id: str, error: str | None = None) -> None:
        state = self._require(job_id)
        with state.condition:
            state.error = error
            state.closed = True
            state.condition.notify_all()

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._streams.pop(job_id, None)

    def get_content_type(self, job_id: str) -> str:
        return self._require(job_id).content_type

    def iter_chunks(self, job_id: str) -> Iterator[bytes]:
        state = self._require(job_id)
        index = 0

        while True:
            with state.condition:
                while index >= len(state.chunks) and not state.closed:
                    state.condition.wait(timeout=1.0)

                if index < len(state.chunks):
                    chunk = state.chunks[index]
                    index += 1
                elif state.closed:
                    break
                else:
                    continue

            yield chunk

    def _require(self, job_id: str) -> _StreamState:
        with self._lock:
            state = self._streams.get(job_id)
        if state is None:
            raise JobAudioStreamNotFoundError(f"Live audio stream not found for job: {job_id}")
        return state
