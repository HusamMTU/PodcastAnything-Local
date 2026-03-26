"""Background execution queue for pipeline jobs."""

from __future__ import annotations

import logging
import queue
import threading

from podcast_anything_local.db.repository import JobRepository
from podcast_anything_local.services.pipeline import PipelineService

logger = logging.getLogger(__name__)


class JobExecutor:
    """Single-worker background executor for queued jobs."""

    def __init__(self, repository: JobRepository, pipeline_service: PipelineService) -> None:
        self._repository = repository
        self._pipeline_service = pipeline_service
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="job-executor", daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._queue.put(None)
        self._thread.join(timeout=3)

    def submit(self, job_id: str) -> None:
        self._queue.put(job_id)

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                self._queue.task_done()
                break
            try:
                self._pipeline_service.run_job(job_id)
            except Exception:
                logger.exception("Job execution failed", extra={"job_id": job_id})
            finally:
                self._queue.task_done()
