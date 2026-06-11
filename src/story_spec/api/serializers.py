"""Serialization of test runs and results to API response format."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from story_spec.core.models import TestRun


def serialize_run(run: TestRun) -> Dict[str, Any]:
    """Convert a TestRun object to a serialized dictionary for API response."""
    # Handle created_at timestamp serialization
    run_created_at = run.created_at
    if isinstance(run_created_at, datetime):
        created_at_seconds = run_created_at.timestamp()
        created_at_iso = run_created_at.astimezone(timezone.utc).isoformat()
    else:
        created_at_seconds = run_created_at
        created_at_iso = datetime.fromtimestamp(run_created_at, tz=timezone.utc).isoformat()
    
    created_at_ms = int(created_at_seconds * 1000)
    
    # Build steps with results
    steps_with_results = []
    result_map = {r.step.index: r for r in run.results}
    
    for step in run.steps:
        res = result_map.get(step.index)
        path = res.screenshot_path if res else None
        screenshot_val = path if path and path.startswith("http") else (Path(path).name if path else None)
        
        steps_with_results.append({
            "index": step.index,
            "action": step.action.value,
            "description": step.description,
            "target": step.target,
            "value": step.value,
            "status": res.status.value if res else "pending",
            "error": res.error if res else None,
            "duration_ms": res.duration_ms if res else 0,
            "screenshot": screenshot_val,
        })
    
    return {
        "id": run.id,
        "url": run.url,
        "story": run.story,
        "created_at": created_at_ms,
        "created_at_seconds": created_at_seconds,
        "created_at_iso": created_at_iso,
        "overall_status": run.overall_status.value,
        "goal_achieved": run.goal_achieved,
        "canceled": run.canceled,
        "cancel_reason": run.cancel_reason,
        "passed": run.passed,
        "failed": run.failed,
        "total_duration_ms": run.total_duration_ms,
        "summary": run.summary,
        "steps": steps_with_results,
    }
