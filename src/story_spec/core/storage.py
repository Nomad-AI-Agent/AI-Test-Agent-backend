import json
import time
from typing import List, Optional
from pathlib import Path
import psycopg2
import psycopg2.extras
from story_spec.core.models import TestRun, TestStep, StepResult, StepStatus, ActionType
from story_spec.core import config


def get_conn():
    conn = psycopg2.connect(config.DATABASE_URL)
    return conn


def init_db():
    if not config.DATABASE_URL:
        return
        
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS test_runs (
                        id TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        story TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        steps_json TEXT NOT NULL,
                        results_json TEXT NOT NULL,
                        summary TEXT,
                        total_duration_ms INTEGER DEFAULT 0,
                        overall_status TEXT DEFAULT 'pending',
                        goal_achieved INTEGER
                    )
                """)
                
                # Check if goal_achieved exists, this is safer in PG
                cur.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='test_runs' and column_name='goal_achieved';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN goal_achieved INTEGER")
            conn.commit()
    except psycopg2.Error as e:
        print(f"Database initialization error: {e}")


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
    goal_achieved_int = None
    if run.goal_achieved is not None:
        goal_achieved_int = 1 if run.goal_achieved else 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO test_runs
                (id, url, story, created_at, steps_json, results_json, summary, total_duration_ms, overall_status, goal_achieved)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                url = EXCLUDED.url,
                story = EXCLUDED.story,
                created_at = EXCLUDED.created_at,
                steps_json = EXCLUDED.steps_json,
                results_json = EXCLUDED.results_json,
                summary = EXCLUDED.summary,
                total_duration_ms = EXCLUDED.total_duration_ms,
                overall_status = EXCLUDED.overall_status,
                goal_achieved = EXCLUDED.goal_achieved
            """, (
                run.id, run.url, run.story, run.created_at,
                steps_json, results_json, run.summary,
                run.total_duration_ms, run.overall_status.value,
                goal_achieved_int
            ))
        conn.commit()


def load_run(run_id: str) -> Optional[TestRun]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM test_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
    if not row:
        return None
    return _row_to_run(row)


def list_runs() -> List[TestRun]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM test_runs ORDER BY created_at DESC")
            rows = cur.fetchall()
            
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

    # Load goal_achieved safely (may be None in old records)
    goal_achieved_raw = None
    try:
        goal_achieved_raw = row["goal_achieved"]
    except (IndexError, KeyError):
        pass
    goal_achieved = None
    if goal_achieved_raw is not None:
        goal_achieved = bool(goal_achieved_raw)

    run = TestRun(
        id=row["id"],
        url=row["url"],
        story=row["story"],
        created_at=row["created_at"],
        steps=steps,
        results=results,
        summary=row["summary"],
        total_duration_ms=row["total_duration_ms"],
        goal_achieved=goal_achieved,
    )
    return run


if config.DATABASE_URL:
    init_db()
