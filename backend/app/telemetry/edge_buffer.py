import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedReading:
    row_id: int
    reading: dict[str, Any]


class EdgeBufferFull(RuntimeError):
    pass


class EdgePublishRejected(RuntimeError):
    def __init__(self, row_id: int, code: str):
        super().__init__(f"Server rejected queued reading {row_id}: {code}.")
        self.row_id = row_id
        self.code = code


class DurableEdgeBuffer:
    def __init__(
        self,
        path: str | Path,
        *,
        max_rows: int | None = None,
        max_batch_readings: int | None = None,
        max_batch_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self.path = str(path)
        self.max_rows = (
            settings.edge_buffer_max_rows if max_rows is None else max_rows
        )
        self.max_batch_readings = (
            settings.edge_batch_max_readings
            if max_batch_readings is None
            else max_batch_readings
        )
        self.max_batch_bytes = (
            settings.edge_batch_max_bytes
            if max_batch_bytes is None
            else max_batch_bytes
        )
        if min(self.max_rows, self.max_batch_readings, self.max_batch_bytes) <= 0:
            raise ValueError("Edge buffer row, batch, and byte limits must be positive.")
        self._connection = sqlite3.connect(self.path, timeout=30)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def enqueue(self, reading: dict[str, Any]) -> int:
        if not isinstance(reading, dict):
            raise ValueError("A reading must be a JSON object.")
        initial = json.dumps(reading, allow_nan=False, separators=(",", ":"))
        with self._connection:
            count = self._connection.execute(
                "SELECT COUNT(*) FROM edge_readings"
            ).fetchone()[0]
            if count >= self.max_rows:
                raise EdgeBufferFull(
                    f"Edge buffer is full at its configured {self.max_rows}-reading limit."
                )
            cursor = self._connection.execute(
                "INSERT INTO edge_readings(payload, created_at) VALUES (?, ?)",
                (initial, datetime.now(UTC).isoformat()),
            )
            row_id = int(cursor.lastrowid)
            queued = dict(reading)
            queued.setdefault("sequence", row_id)
            queued.setdefault("source_event_id", f"edge-{uuid.uuid4().hex}")
            payload = json.dumps(queued, allow_nan=False, separators=(",", ":"))
            if len(payload.encode("utf-8")) > self.max_batch_bytes:
                raise ValueError("Reading exceeds the configured edge batch byte limit.")
            self._connection.execute(
                "UPDATE edge_readings SET payload = ? WHERE id = ?",
                (payload, row_id),
            )
        return row_id

    def peek_batch(self) -> list[QueuedReading]:
        rows = self._connection.execute(
            "SELECT id, payload FROM edge_readings ORDER BY id LIMIT ?",
            (self.max_batch_readings,),
        ).fetchall()
        batch: list[QueuedReading] = []
        size = 0
        for row_id, payload in rows:
            item_size = len(payload.encode("utf-8"))
            separator_size = 1 if batch else 0
            envelope_size = len(b'{"readings":[]}') + size + separator_size + item_size
            if batch and envelope_size > self.max_batch_bytes:
                break
            if len(b'{"readings":[]}') + item_size > self.max_batch_bytes:
                raise ValueError(
                    f"Queued reading {row_id} exceeds the configured edge batch byte limit."
                )
            batch.append(QueuedReading(row_id=row_id, reading=json.loads(payload)))
            size += item_size
        return batch

    def acknowledge(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        with self._connection:
            self._connection.executemany(
                "DELETE FROM edge_readings WHERE id = ?",
                [(row_id,) for row_id in row_ids],
            )

    def count(self) -> int:
        return int(
            self._connection.execute("SELECT COUNT(*) FROM edge_readings").fetchone()[0]
        )

    def close(self) -> None:
        self._connection.close()


class RestEdgePublisher:
    def __init__(
        self,
        buffer: DurableEdgeBuffer,
        *,
        api_url: str,
        credential: str,
        timeout_seconds: float = 10,
    ) -> None:
        if not api_url.startswith("https://") and not api_url.startswith("http://127.0.0.1"):
            raise ValueError("Edge API URL must use HTTPS, except for loopback development.")
        if not credential:
            raise ValueError("A scoped device credential is required.")
        self.buffer = buffer
        self.api_url = api_url.rstrip("/") + "/telemetry/readings"
        self.credential = credential
        self.timeout_seconds = timeout_seconds

    def publish_pending(
        self,
        post_batch: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> int:
        published = 0
        while batch := self.buffer.peek_batch():
            readings = [item.reading for item in batch]
            responses = (
                post_batch(readings)
                if post_batch is not None
                else self._post_http(readings)
            )
            if len(responses) != len(batch):
                raise ValueError("Telemetry API response count did not match the edge batch.")
            acknowledged: list[int] = []
            for queued, response in zip(batch, responses):
                status = response.get("status")
                if status in {"accepted", "duplicate"}:
                    acknowledged.append(queued.row_id)
                    published += status == "accepted"
                elif status == "rejected":
                    raise EdgePublishRejected(
                        queued.row_id, str(response.get("code", "REJECTED"))
                    )
                else:
                    raise ValueError("Telemetry API returned an unknown item status.")
            self.buffer.acknowledge(acknowledged)
        return published

    def run_forever(self, stop_event) -> None:
        settings = get_settings()
        delay = settings.edge_retry_base_seconds
        while not stop_event.is_set():
            try:
                self.publish_pending()
                delay = settings.edge_retry_base_seconds
            except (URLError, TimeoutError, OSError) as error:
                logger.warning(
                    "Edge connection failed; retrying with bounded backoff (error_type=%s).",
                    type(error).__name__,
                )
                stop_event.wait(delay)
                delay = min(delay * 2, settings.edge_retry_max_seconds)
            except EdgePublishRejected:
                raise

    def _post_http(self, readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        body = json.dumps({"readings": readings}, allow_nan=False).encode("utf-8")
        if len(body) > self.buffer.max_batch_bytes:
            raise ValueError("Serialized edge batch exceeds the configured byte limit.")
        request = Request(
            self.api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.credential}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read(self.buffer.max_batch_bytes + 1))
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError("Telemetry API response has no item results.")
        return results
