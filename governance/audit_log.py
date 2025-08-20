"""
Audit Log

Every agent action — approved, escalated, or blocked — gets written
here before anything else happens. This is the "glass box" that lets
Finance, Compliance, and Ops see exactly what the agents did and why.

Storage: SQLite (zero setup, easy to query, portable for demos).
In production you'd swap this for BigQuery or Cloud Spanner.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "audit.db")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    sender      TEXT    NOT NULL,
    recipient   TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    verdict     TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    payload     TEXT,           -- JSON blob
    result      TEXT,           -- JSON blob
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_id    ON audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_verdict    ON audit_log(verdict);
CREATE INDEX IF NOT EXISTS idx_created_at ON audit_log(created_at);
"""


class AuditLog:

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(CREATE_TABLE)
        logger.info("[AuditLog] Database ready at %s", self.db_path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        task_id:   str,
        sender:    str,
        recipient: str,
        action:    str,
        verdict:   str,
        reason:    str,
        payload:   Optional[Dict] = None,
        result:    Optional[Dict] = None,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                    (task_id, sender, recipient, action, verdict, reason,
                     payload, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    sender,
                    recipient,
                    action,
                    verdict,
                    reason,
                    json.dumps(payload) if payload else None,
                    json.dumps(result)  if result  else None,
                    datetime.utcnow().isoformat(),
                ),
            )
        logger.debug(
            "[AuditLog] %s | %s → %s | verdict=%s",
            task_id[:8], sender, action, verdict
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_recent(self, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_verdict(self, verdict: str, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE verdict = ? ORDER BY created_at DESC LIMIT ?",
                (verdict, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_task(self, task_id: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_stats(self) -> Dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            by_verdict = conn.execute(
                "SELECT verdict, COUNT(*) as cnt FROM audit_log GROUP BY verdict"
            ).fetchall()
            by_action = conn.execute(
                "SELECT action, COUNT(*) as cnt FROM audit_log GROUP BY action ORDER BY cnt DESC LIMIT 5"
            ).fetchall()

        return {
            "total":      total,
            "by_verdict": {r["verdict"]: r["cnt"] for r in by_verdict},
            "top_actions": [{"action": r["action"], "count": r["cnt"]} for r in by_action],
        }

    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        d = dict(row)
        if d.get("payload"):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get("result"):
            try:
                d["result"] = json.loads(d["result"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d

# get_stats(): verdict breakdown dict used by dashboard and CLI summary
