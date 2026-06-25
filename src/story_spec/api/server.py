import os
import asyncio
import json
import time
import threading
from typing import Optional, Dict, List
import io
from urllib.parse import urlparse
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
from story_spec.core import storage
from story_spec.core import config
from story_spec.core import supabase
from story_spec.core.models import TargetConfig
from story_spec.api.auth import router as auth_router
from story_spec.api.deps import get_optional_user
from story_spec.db.models import User

app = FastAPI(title="StorySpec AI — Quiet Intelligence")
app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

_run_events: dict = {}   # run_id -> list[dict]
_run_done:   dict = {}   # run_id -> bool
_run_cancel: dict = {}   # run_id -> bool
_run_cancel_reason: dict = {}  # run_id -> str
_run_pause: dict = {}   # run_id -> bool
_run_pause_reason: dict = {}  # run_id -> str
_run_tasks:  dict = {}   # run_id -> (loop, task)
_run_state_lock = threading.Lock()


def _push_event(run_id: str, data: dict):
    if run_id not in _run_events:
        _run_events[run_id] = []
    _run_events[run_id].append(data)


class TargetRequest(BaseModel):
    url: str
    role: Optional[str] = None


class RunRequest(BaseModel):
    targets: Optional[List[TargetRequest]] = None
    url: Optional[str] = None  # backward compat: single URL
    story: str
    headless: bool = True


class RunCancelRequest(BaseModel):
    reason: Optional[str] = "Run canceled by user."


class RunPauseRequest(BaseModel):
    reason: Optional[str] = "Run paused by user."



@app.get("/api/runs")
async def api_list_runs(
    current_user: Optional[User] = Depends(get_optional_user),
):
    runs = storage.list_runs()
    if current_user:
        runs = [r for r in runs if r.user_id == str(current_user.id)]
    return [_run_to_dict(r) for r in runs]


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_dict(run)


@app.post("/api/runs")
async def api_create_run(
    req: RunRequest,
    background_tasks: BackgroundTasks,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Start a new test run asynchronously and return the run ID immediately."""
    from story_spec.core.runner import create_run

    # Backward compat: accept either targets[] or url
    if req.targets:
        targets = [TargetConfig(url=t.url, role=t.role) for t in req.targets]
    elif req.url:
        targets = [TargetConfig(url=req.url)]
    else:
        raise HTTPException(status_code=422, detail="Provide either 'targets' (array) or 'url' (string)")

    run = create_run(targets, req.story, user_id=str(current_user.id) if current_user else None)
    storage.save_run(run)
    _run_events[run.id] = []
    _run_done[run.id] = False
    _run_cancel[run.id] = False
    _run_cancel_reason[run.id] = "Run canceled by user."

    background_tasks.add_task(_execute_run, run.id, targets, req.story, req.headless, None)
    return {"run_id": run.id}


@app.post("/api/runs/{run_id}/cancel")
async def api_cancel_run(run_id: str, req: Optional[RunCancelRequest] = None):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if _run_done.get(run_id, False):
        return {"run_id": run_id, "status": run.overall_status.value, "message": "Run already finished"}

    reason = (req.reason if req else None) or "Run canceled by user."
    with _run_state_lock:
        task_state = _run_tasks.get(run_id)
    if task_state:
        loop, task = task_state
        if task.done():
            return {"run_id": run_id, "status": run.overall_status.value, "message": "Run already finished"}

    _run_cancel[run_id] = True
    _run_cancel_reason[run_id] = reason
    if task_state:
        loop, task = task_state
        loop.call_soon_threadsafe(task.cancel)

    _push_event(run_id, {
        "type": "cancel_requested",
        "message": reason,
    })
    return {"run_id": run_id, "status": "cancel_requested"}


@app.post("/api/runs/{run_id}/pause")
async def api_pause_run(run_id: str, req: Optional[RunPauseRequest] = None):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.paused:
        return {"run_id": run_id, "status": "paused", "message": "Run already paused"}
    if _run_done.get(run_id, False):
        return {"run_id": run_id, "status": run.overall_status.value, "message": "Run already finished"}

    reason = (req.reason if req else None) or "Run paused by user."
    _run_pause[run_id] = True
    _run_pause_reason[run_id] = reason

    _push_event(run_id, {
        "type": "pause_requested",
        "message": reason,
    })
    return {"run_id": run_id, "status": "pause_requested"}


@app.post("/api/runs/{run_id}/resume")
async def api_resume_run(run_id: str, background_tasks: BackgroundTasks):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.paused or not run.pause_checkpoint:
        return {"run_id": run_id, "status": run.overall_status.value, "message": "Run is not paused or has no checkpoint"}

    if not _run_done.get(run_id, True):
        return {"run_id": run_id, "status": run.overall_status.value, "message": "Run is already executing"}

    checkpoint = run.pause_checkpoint

    # Reset in-memory pause flags; runner clears persisted paused state on start
    _run_pause[run_id] = False
    _run_pause_reason[run_id] = None

    # Resume execution with checkpoint
    _run_events[run_id] = []
    _run_done[run_id] = False
    _run_cancel[run_id] = False
    _run_cancel_reason[run_id] = "Run canceled by user."

    background_tasks.add_task(
        _execute_run,
        run.id,
        run.targets,
        run.story,
        True,  # headless
        checkpoint
    )

    _push_event(run_id, {
        "type": "resumed",
        "message": "Run resumed from checkpoint",
    })
    return {"run_id": run_id, "status": "resumed"}


@app.get("/api/runs/{run_id}/stream")
async def api_stream_run(run_id: str):
    """Server-Sent Events stream for live run progress."""
    async def event_generator():
        sent = 0
        while True:
            events = _run_events.get(run_id, [])
            while sent < len(events):
                ev = events[sent]
                yield f"data: {json.dumps(ev)}\n\n"
                sent += 1
            if _run_done.get(run_id):
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/screenshot/{run_id}/{filename:path}")
async def screenshot(run_id: str, filename: str, request: Request):
    # If the filename is a full URL, extract just the filename from the path
    if filename.startswith("http"):
        # Extract filename from URL path (e.g., .../step_00.png?token=... -> step_00.png)
        parsed = urlparse(filename)
        # Get the last part of the path
        actual_filename = parsed.path.split("/")[-1]
    else:
        actual_filename = filename

    # Try to download from Supabase first (permanent access via service key)
    image_data = supabase.download_screenshot(run_id, actual_filename)
    if image_data:
        return StreamingResponse(io.BytesIO(image_data), media_type="image/png")

    # Fallback to local file storage
    path = config.SCREENSHOTS_DIR / run_id / actual_filename
    if path.exists():
        return FileResponse(str(path), media_type="image/png")

    raise HTTPException(status_code=404, detail="Screenshot not found")


@app.get("/video/{run_id}")
async def video(run_id: str):
    run = storage.load_run(run_id)
    if not run or not run.video_path:
        raise HTTPException(status_code=404, detail="Video not found")

    video_path = run.video_path

    # If it's a Supabase URL, redirect to it
    if video_path.startswith("http"):
        return RedirectResponse(url=video_path)

    # Serve local file
    path = Path(video_path)
    if path.exists():
        return FileResponse(str(path), media_type="video/webm")

    raise HTTPException(status_code=404, detail="Video file not found")


@app.get("/")
async def root():
    return {"status": "StorySpec AI API is running."}


def _execute_run(run_id: str, targets, story: str, headless: bool, resume_from_checkpoint: Optional[Dict] = None):
    """Run the agentic pipeline in a thread and push SSE events."""
    from story_spec.core.models import StepStatus

    def on_progress(rid, i, total, step, result):
        path = result.screenshot_path
        screenshot_val = path if path and path.startswith("http") else (Path(path).name if path else None)
        _push_event(rid, {
            "type": "step",
            "step_index": i,
            "action": step.action.value,
            "description": step.description,
            "status": result.status.value,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "screenshot": screenshot_val,
            "target_index": step.target_index,
        })

    from story_spec.core import runner
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = loop.create_task(
            runner.execute(
                targets,
                story,
                headless=headless,
                on_progress=on_progress,
                run_id=run_id,
                should_cancel=lambda: _run_cancel.get(run_id, False),
                cancel_reason=lambda: _run_cancel_reason.get(run_id),
                should_pause=lambda: _run_pause.get(run_id, False),
                pause_reason=lambda: _run_pause_reason.get(run_id),
                resume_from_checkpoint=resume_from_checkpoint,
            )
        )
        with _run_state_lock:
            _run_tasks[run_id] = (loop, task)
        completed = loop.run_until_complete(task)
        
        # Check if run was paused
        if completed.paused:
            _push_event(run_id, {
                "type": "paused",
                "message": _run_pause_reason.get(run_id, "Run paused"),
                "checkpoint": completed.pause_checkpoint,
            })
        else:
            _push_event(run_id, {
                "type": "finished",
                "overall_status": completed.overall_status.value,
                "passed": completed.passed,
                "failed": completed.failed,
                "total_duration_ms": completed.total_duration_ms,
                "goal_achieved": completed.goal_achieved,
                "canceled": completed.canceled,
                "cancel_reason": completed.cancel_reason,
                "paused": completed.paused,
                "summary": completed.summary,
                "video_url": f"/video/{run_id}" if completed.video_path else None,
            })
    except Exception as exc:
        _push_event(run_id, {"type": "error", "message": str(exc)})
    finally:
        with _run_state_lock:
            _run_tasks.pop(run_id, None)
        _run_done[run_id] = True
        _run_cancel.pop(run_id, None)
        _run_cancel_reason.pop(run_id, None)
        _run_pause.pop(run_id, None)
        _run_pause_reason.pop(run_id, None)
        if loop is not None:
            loop.close()


def _run_to_dict(run) -> dict:
    run_created_at = run.created_at
    if isinstance(run_created_at, datetime):
        created_at_seconds = run_created_at.timestamp()
        created_at_iso = run_created_at.astimezone(timezone.utc).isoformat()
    else:
        created_at_seconds = run_created_at
        created_at_iso = datetime.fromtimestamp(run_created_at, tz=timezone.utc).isoformat()
    created_at_ms = int(created_at_seconds * 1000)
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
            "target_index": step.target_index,
        })
    return {
        "id": run.id,
        "user_id": run.user_id,
        "targets": [{"url": t.url, "role": t.role} for t in run.targets],
        "url": run.url,
        "story": run.story,
        "created_at": created_at_ms,
        "created_at_seconds": created_at_seconds,
        "created_at_iso": created_at_iso,
        "overall_status": run.overall_status.value,
        "goal_achieved": run.goal_achieved,
        "canceled": run.canceled,
        "cancel_reason": run.cancel_reason,
        "paused": run.paused,
        "passed": run.passed,
        "failed": run.failed,
        "total_duration_ms": run.total_duration_ms,
        "summary": run.summary,
        "steps": steps_with_results,
        "video_url": f"/video/{run.id}" if run.video_path else None,
    }


def start():
    import uvicorn
    host = config.DASHBOARD_HOST
    port = config.DASHBOARD_PORT
    
    # Railway sets PORT env var
    if os.environ.get('PORT'):
        port = int(os.environ['PORT'])
        host = "0.0.0.0"
    
    server_url = f"http://{host}:{port}"
    print()
    print(f"StorySpec AI API starting at {server_url}")
    print("Press Ctrl+C to stop the server.")
    print()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start()
