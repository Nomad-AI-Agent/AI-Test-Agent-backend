import sqlite3
import json
import time
from typing import List, Optional
from pathlib import Path
from models import TestRun, TestStep, StepResult, StepStatus, ActionType
import config


def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS test_runs (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                story TEXT NOT NULL,
                created_at REAL NOT NULL,
                steps_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                summary TEXT,
                total_duration_ms INTEGER DEFAULT 0,
                overall_status TEXT DEFAULT 'pending'
            )
        """)
        conn.commit()


def save_run(run: TestRun):
    steps_json = json.dumps([
        {
            "index": s.index,
            "action": s.action.value,
            "description": s.description,
            "target": s.target,
            "value": s.value,
            "assertion": s.assertion,
        }
        for s in run.steps
    ])
    results_json = json.dumps([
        {
            "step_index": r.step.index,
            "status": r.status.value,
            "screenshot_path": r.screenshot_path,
            "error": r.error,
            "duration_ms": r.duration_ms,
        }
        for r in run.results
    ])
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO test_runs
            (id, url, story, created_at, steps_json, results_json, summary, total_duration_ms, overall_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run.id, run.url, run.story, run.created_at,
            steps_json, results_json, run.summary,
            run.total_duration_ms, run.overall_status.value
        ))
        conn.commit()


def load_run(run_id: str) -> Optional[TestRun]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return _row_to_run(row)


def list_runs() -> List[TestRun]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM test_runs ORDER BY created_at DESC").fetchall()
    return [_row_to_run(r) for r in rows]


def _row_to_run(row) -> TestRun:
    steps_data = json.loads(row["steps_json"])
    results_data = json.loads(row["results_json"])

    steps = [
        TestStep(
            index=s["index"],
            action=ActionType(s["action"]),
            description=s["description"],
            target=s.get("target"),
            value=s.get("value"),
            assertion=s.get("assertion"),
        )
        for s in steps_data
    ]

    step_map = {s.index: s for s in steps}
    results = [
        StepResult(
            step=step_map[r["step_index"]],
            status=StepStatus(r["status"]),
            screenshot_path=r.get("screenshot_path"),
            error=r.get("error"),
            duration_ms=r.get("duration_ms", 0),
        )
        for r in results_data
        if r["step_index"] in step_map
    ]

    run = TestRun(
        id=row["id"],
        url=row["url"],
        story=row["story"],
        created_at=row["created_at"],
        steps=steps,
        results=results,
        summary=row["summary"],
        total_duration_ms=row["total_duration_ms"],
    )
    return run


init_db()
