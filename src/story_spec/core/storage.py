import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pathlib import Path
import psycopg2
import psycopg2.extras
from story_spec.core.models import TestRun, TestStep, StepResult, StepStatus, ActionType, TargetConfig
from story_spec.core import config


SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_USER_EMAIL = "system@story-spec.local"
SYSTEM_USERNAME = "system"


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
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        steps_json TEXT NOT NULL,
                        results_json TEXT NOT NULL,
                        summary TEXT,
                        total_duration_ms INTEGER DEFAULT 0,
                        overall_status TEXT DEFAULT 'pending',
                        goal_achieved INTEGER,
                        canceled INTEGER DEFAULT 0,
                        cancel_reason TEXT
                    )
                """)
                
                # Add targets_json for multi-role support
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='test_runs' and column_name='targets_json';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN targets_json TEXT")

                # Check if goal_achieved exists, this is safer in PG
                cur.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='test_runs' and column_name='goal_achieved';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN goal_achieved INTEGER")
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='test_runs' and column_name='canceled';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN canceled INTEGER DEFAULT 0")
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='test_runs' and column_name='cancel_reason';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN cancel_reason TEXT")
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='test_runs' and column_name='paused';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN paused INTEGER DEFAULT 0")
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='test_runs' and column_name='pause_checkpoint';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN pause_checkpoint TEXT")
                cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='test_runs' and column_name='video_path';
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE test_runs ADD COLUMN video_path TEXT")

                created_at_type = _column_data_type(cur, "created_at")
                if created_at_type == "double precision":
                    cur.execute("""
                        ALTER TABLE test_runs
                        ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE
                        USING to_timestamp(created_at) AT TIME ZONE 'UTC'
                    """)
                conn.commit()
    except psycopg2.Error as e:
        print(f"Database initialization error: {e}")


def _test_runs_columns(cur) -> set[str]:
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'test_runs'
    """)
    return {row[0] for row in cur.fetchall()}


def _uses_timestamp_created_at(cur) -> bool:
    return _column_data_type(cur, "created_at") in {
        "timestamp without time zone",
        "timestamp with time zone",
    }


def _column_data_type(cur, column_name: str) -> Optional[str]:
    cur.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = 'test_runs' AND column_name = %s
    """, (column_name,))
    row = cur.fetchone()
    return row[0] if row else None


def _ensure_system_user(cur) -> str:
    cur.execute("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'users'
    """)
    if not cur.fetchone():
        return str(SYSTEM_USER_ID)

    cur.execute("SELECT id FROM users WHERE id = %s", (str(SYSTEM_USER_ID),))
    row = cur.fetchone()
    if row:
        return str(row[0])

    cur.execute("""
        INSERT INTO users (
            id, email, username, full_name, hashed_password,
            is_active, email_verified
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
        RETURNING id
    """, (
        str(SYSTEM_USER_ID),
        SYSTEM_USER_EMAIL,
        SYSTEM_USERNAME,
        "System User",
        "disabled",
        True,
        True,
    ))
    inserted = cur.fetchone()
    return str(inserted[0]) if inserted else str(SYSTEM_USER_ID)


def save_run(run: TestRun):
    targets_json = json.dumps([
        {"url": t.url, "role": t.role}
        for t in run.targets
    ])
    steps_json = json.dumps([
        {
            "index": s.index,
            "action": s.action.value,
            "description": s.description,
            "target": s.target,
            "value": s.value,
            "assertion": s.assertion,
            "target_index": s.target_index,
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
    canceled_int = 1 if run.canceled else 0
    paused_int = 1 if run.paused else 0
    pause_checkpoint_json = json.dumps(run.pause_checkpoint) if run.pause_checkpoint else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            columns = _test_runs_columns(cur)
            created_at_is_timestamp = _uses_timestamp_created_at(cur)
            goal_achieved_type = _column_data_type(cur, "goal_achieved")
            created_at_value = run.created_at
            if created_at_is_timestamp:
                if isinstance(run.created_at, datetime):
                    created_at_value = run.created_at.astimezone(timezone.utc)
                else:
                    created_at_value = datetime.fromtimestamp(run.created_at, tz=timezone.utc)
            elif isinstance(run.created_at, datetime):
                created_at_value = run.created_at.timestamp()

            insert_columns = [
                "id",
                "url",
                "targets_json",
                "story",
                "created_at",
                "steps_json",
                "results_json",
                "summary",
                "total_duration_ms",
                "overall_status",
                "goal_achieved",
                "canceled",
                "cancel_reason",
                "paused",
                "pause_checkpoint",
                "video_path",
            ]
            insert_values = [
                run.id,
                run.url,
                targets_json,
                run.story,
                created_at_value,
                steps_json,
                results_json,
                run.summary,
                run.total_duration_ms,
                run.overall_status.value,
                run.goal_achieved if goal_achieved_type == "boolean" else goal_achieved_int,
                canceled_int,
                run.cancel_reason,
                paused_int,
                pause_checkpoint_json,
                run.video_path,
            ]

            if "user_id" in columns:
                insert_columns.insert(1, "user_id")
                insert_values.insert(1, _ensure_system_user(cur))

            if "updated_at" in columns:
                insert_columns.append("updated_at")
                insert_values.append(created_at_value)

            assignments = ",\n                ".join(
                f"{column} = EXCLUDED.{column}"
                for column in insert_columns
                if column not in {"id", "user_id"}
            )
            placeholders = ", ".join(["%s"] * len(insert_columns))
            column_sql = ", ".join(insert_columns)

            cur.execute(f"""
                INSERT INTO test_runs
                ({column_sql})
                VALUES ({placeholders})
                ON CONFLICT (id) DO UPDATE SET
                {assignments}
            """, tuple(insert_values))
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
    # Load targets with backward compatibility
    try:
        targets_raw = row.get("targets_json")
    except (IndexError, KeyError):
        targets_raw = None
    if targets_raw:
        targets_data = json.loads(targets_raw)
        targets = [TargetConfig(url=t["url"], role=t.get("role")) for t in targets_data]
    else:
        # Legacy: single URL, no role
        targets = [TargetConfig(url=row["url"], role=None)]

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
            target_index=s.get("target_index", 0),
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

    canceled_raw = None
    try:
        canceled_raw = row["canceled"]
    except (IndexError, KeyError):
        pass
    canceled = bool(canceled_raw) if canceled_raw is not None else False

    cancel_reason = None
    try:
        cancel_reason = row["cancel_reason"]
    except (IndexError, KeyError):
        pass

    paused_raw = None
    try:
        paused_raw = row["paused"]
    except (IndexError, KeyError):
        pass
    paused = bool(paused_raw) if paused_raw is not None else False

    pause_checkpoint = None
    try:
        pause_checkpoint_raw = row["pause_checkpoint"]
        if pause_checkpoint_raw:
            pause_checkpoint = json.loads(pause_checkpoint_raw)
    except (IndexError, KeyError):
        pass

    video_path = None
    try:
        video_path = row["video_path"]
    except (IndexError, KeyError):
        pass

    created_at = row["created_at"]
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = datetime.fromtimestamp(created_at, tz=timezone.utc)

    run = TestRun(
        id=row["id"],
        targets=targets,
        story=row["story"],
        created_at=created_at,
        steps=steps,
        results=results,
        summary=row["summary"],
        total_duration_ms=row["total_duration_ms"],
        goal_achieved=goal_achieved,
        canceled=canceled,
        cancel_reason=cancel_reason,
        paused=paused,
        pause_checkpoint=pause_checkpoint,
        video_path=video_path,
    )
    return run


if config.DATABASE_URL:
    init_db()
