import sys
import os
import asyncio
import json
import time
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from story_spec.core import storage
from story_spec.core import config

app = FastAPI(title="StorySpec AI — Quiet Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

_run_events: dict = {}   # run_id -> list[dict]
_run_done:   dict = {}   # run_id -> bool


def _push_event(run_id: str, data: dict):
    if run_id not in _run_events:
        _run_events[run_id] = []
    _run_events[run_id].append(data)


class RunRequest(BaseModel):
    url: str
    story: str
    headless: bool = True



@app.get("/api/runs")
async def api_list_runs():
    runs = storage.list_runs()
    return [_run_to_dict(r) for r in runs]


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_dict(run)


@app.post("/api/runs")
async def api_create_run(req: RunRequest, background_tasks: BackgroundTasks):
    """Start a new test run asynchronously and return the run ID immediately."""
    from story_spec.core.runner import create_run
    run = create_run(req.url, req.story)
    storage.save_run(run)
    _run_events[run.id] = []
    _run_done[run.id] = False

    background_tasks.add_task(_execute_run, run.id, req.url, req.story, req.headless)
    return {"run_id": run.id}


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
    # If the filename is actually a full URL (happens if frontend prefixes the Supabase URL)
    if filename.startswith("http"):
        # Append query parameters (like tokens for signed URLs) if present
        query = request.url.query
        full_url = f"{filename}?{query}" if query else filename
        return RedirectResponse(full_url)
        
    path = config.SCREENSHOTS_DIR / run_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/")
async def root():
    return {"status": "StorySpec AI API is running."}


def _execute_run(run_id: str, url: str, story: str, headless: bool):
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
        })

    from story_spec.core import runner
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        completed = loop.run_until_complete(
            runner.execute(url, story, headless=headless, on_progress=on_progress, run_id=run_id)
        )
        _push_event(run_id, {
            "type": "finished",
            "overall_status": completed.overall_status.value,
            "passed": completed.passed,
            "failed": completed.failed,
            "total_duration_ms": completed.total_duration_ms,
            "goal_achieved": completed.goal_achieved,
            "summary": completed.summary,
        })
    except Exception as exc:
        _push_event(run_id, {"type": "error", "message": str(exc)})
    finally:
        _run_done[run_id] = True


def _run_to_dict(run) -> dict:
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
        "created_at": run.created_at,
        "overall_status": run.overall_status.value,
        "goal_achieved": run.goal_achieved,
        "passed": run.passed,
        "failed": run.failed,
        "total_duration_ms": run.total_duration_ms,
        "summary": run.summary,
        "steps": steps_with_results,
    }


def start():
    import uvicorn
    uvicorn.run(app, host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, log_level="warning")


if __name__ == "__main__":
    start()
