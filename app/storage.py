from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from app.models import IterationResult, RunConfig, RunInput, RunSnapshot, RunState


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    summary TEXT,
                    best_iteration INTEGER,
                    best_score INTEGER,
                    stop_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS iterations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    iteration_index INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                """
            )

    def create_run(self, run_id: str, payload: RunInput, config: RunConfig) -> None:
        with self._conn() as conn:
            timestamp = now_iso()
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, state, payload_json, config_json, summary,
                    best_iteration, best_score, stop_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    run_id,
                    RunState.PENDING,
                    payload.model_dump_json(),
                    config.model_dump_json(),
                    timestamp,
                    timestamp,
                ),
            )

    def update_run_state(self, run_id: str, state: RunState) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (state, now_iso(), run_id),
            )

    def save_iteration(self, run_id: str, result: IterationResult) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO iterations (run_id, iteration_index, result_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    result.index,
                    result.model_dump_json(),
                    now_iso(),
                ),
            )

    def finalize_run(
        self,
        run_id: str,
        summary: str,
        best_iteration: int,
        best_score: int,
        stop_reason: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET state = ?, summary = ?, best_iteration = ?, best_score = ?,
                    stop_reason = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    RunState.COMPLETED,
                    summary,
                    best_iteration,
                    best_score,
                    stop_reason,
                    now_iso(),
                    run_id,
                ),
            )

    def fail_run(self, run_id: str, reason: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET state = ?, summary = ?, stop_reason = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (RunState.FAILED, "Run failed before completion.", reason, now_iso(), run_id),
            )

    def get_run(self, run_id: str) -> RunSnapshot | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            return RunSnapshot(
                run_id=row["run_id"],
                state=RunState(row["state"]),
                payload=json.loads(row["payload_json"]),
                config=json.loads(row["config_json"]),
                summary=row["summary"],
                best_iteration=row["best_iteration"],
                best_score=row["best_score"],
                stop_reason=row["stop_reason"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_runs(self, limit: int = 12) -> list[RunSnapshot]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                RunSnapshot(
                    run_id=row["run_id"],
                    state=RunState(row["state"]),
                    payload=json.loads(row["payload_json"]),
                    config=json.loads(row["config_json"]),
                    summary=row["summary"],
                    best_iteration=row["best_iteration"],
                    best_score=row["best_score"],
                    stop_reason=row["stop_reason"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    def list_iterations(self, run_id: str) -> list[IterationResult]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT result_json FROM iterations
                WHERE run_id = ?
                ORDER BY iteration_index ASC
                """,
                (run_id,),
            ).fetchall()
            return [IterationResult.model_validate_json(row["result_json"]) for row in rows]

