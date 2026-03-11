"""In-memory event streaming for job progress."""

from __future__ import annotations

import json
import queue
import threading
from collections import defaultdict
from collections.abc import Iterator


class JobEventBroker:
    """Broadcast rewrite events to zero or more SSE subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[queue.Queue[dict[str, object]]]] = defaultdict(list)
        self._rewrite_snapshots: dict[str, str] = {}
        self._terminal_events: dict[str, dict[str, object]] = {}

    def publish_rewrite_chunk(self, job_id: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._rewrite_snapshots[job_id] = f"{self._rewrite_snapshots.get(job_id, '')}{text}"
            subscribers = list(self._subscribers.get(job_id, []))
        self._publish_to_subscribers(subscribers, "rewrite_chunk", {"text": text})

    def publish_rewrite_complete(self, job_id: str) -> None:
        event = {"event": "rewrite_complete", "data": {}}
        with self._lock:
            self._terminal_events[job_id] = event
            subscribers = list(self._subscribers.get(job_id, []))
        self._publish_to_subscribers(subscribers, event["event"], event["data"])

    def publish_job_failed(self, job_id: str, error: str) -> None:
        event = {"event": "job_failed", "data": {"error": error}}
        with self._lock:
            self._terminal_events[job_id] = event
            subscribers = list(self._subscribers.get(job_id, []))
        self._publish_to_subscribers(subscribers, event["event"], event["data"])

    def get_rewrite_snapshot(self, job_id: str) -> str:
        with self._lock:
            return self._rewrite_snapshots.get(job_id, "")

    def stream(self, job_id: str) -> Iterator[str]:
        subscriber: queue.Queue[dict[str, object]] = queue.Queue()
        with self._lock:
            self._subscribers[job_id].append(subscriber)
            snapshot = self._rewrite_snapshots.get(job_id, "")
            terminal_event = self._terminal_events.get(job_id)

        try:
            if snapshot:
                yield _encode_sse_event("rewrite_snapshot", {"text": snapshot})

            if terminal_event is not None:
                yield _encode_sse_event(
                    str(terminal_event["event"]),
                    dict(terminal_event["data"]),
                )
                return

            while True:
                try:
                    event = subscriber.get(timeout=1.0)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue

                event_name = str(event["event"])
                data = dict(event["data"])
                yield _encode_sse_event(event_name, data)
                if event_name in {"rewrite_complete", "job_failed"}:
                    return
        finally:
            with self._lock:
                subscribers = self._subscribers.get(job_id, [])
                if subscriber in subscribers:
                    subscribers.remove(subscriber)
                if not subscribers:
                    self._subscribers.pop(job_id, None)

    def _publish_to_subscribers(
        self,
        subscribers: list[queue.Queue[dict[str, object]]],
        event_name: str,
        data: dict[str, object],
    ) -> None:
        payload = {"event": event_name, "data": data}
        for subscriber in subscribers:
            subscriber.put(payload)


def _encode_sse_event(event_name: str, data: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"
