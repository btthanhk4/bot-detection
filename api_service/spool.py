"""Durable local queue for telemetry accepted during a MongoDB outage."""

import json
import os
import sqlite3
import threading
from contextlib import closing


class TelemetrySpool:
    def __init__(self, path: str, capacity: int):
        self.path = os.fspath(path)
        self.capacity = capacity
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA synchronous=FULL")
        if not self._initialized:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS telemetry_spool ("
                "id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.commit()
            self._initialized = True
        return connection

    def enqueue(self, event: dict):
        payload = json.dumps(event, ensure_ascii=True, allow_nan=False)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("SELECT COUNT(*) FROM telemetry_spool").fetchone()[0]
            if count >= self.capacity:
                connection.rollback()
                return None
            cursor = connection.execute(
                "INSERT INTO telemetry_spool(session_id, payload) VALUES (?, ?)",
                (str(event.get("sessionId") or ""), payload),
            )
            connection.commit()
            return cursor.lastrowid

    def load(self) -> list[dict]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, payload FROM telemetry_spool ORDER BY id"
            ).fetchall()
        return [{**json.loads(payload), "_spool_id": identifier} for identifier, payload in rows]

    def delete(self, identifier: int) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("DELETE FROM telemetry_spool WHERE id = ?", (identifier,))
            connection.commit()

    def delete_session(self, session_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("DELETE FROM telemetry_spool WHERE session_id = ?", (session_id,))
            connection.commit()

    def clear(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("DELETE FROM telemetry_spool")
            connection.commit()

    def count(self) -> int:
        with self._lock, closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM telemetry_spool").fetchone()[0]
