import os
import asyncio
import json
import time
from typing import Optional
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from story_spec.core import storage, config
from story_spec.core.observability import setup_langsmith
from story_spec.api.schemas import RunRequest, RunCancelRequest
from story_spec.api import events, serializers, screenshots

app = FastAPI(title="StorySpec AI — Quiet Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)



@app.get("/api/runs")
async def api_list_runs():
    runs = storage.list_runs()
    return [serializers.serialize_run(r) for r in runs]


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return serializers.serialize_run(run)


@app.post("/api/runs")
async def api_create_run(req: RunRequest, background_tasks: BackgroundTasks):
    """Start a new test run asynchronously and return the run ID immediately."""
    from story_spec.core.runner import create_run
    run = create_run(req.url, req.story)
    storage.save_run(run)
    events.initialize_run(run.id)

    background_tasks.add_task(_execute_run, run.id, req.url, req.story, req.headless)
    return {"run_id": run.id}


@app.post("/api/runs/{run_id}/cancel")
async def api_cancel_run(run_id: str, req: Optional[RunCancelRequest] = None):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if events.is_done(run_id):
        return {"run_id": run_id, "status": run.overall_status.value, "message": "Run already finished"}

    events.request_cancel(run_id)
    reason = (req.reason if req else None) or "Run canceled by user."
    events.push_event(run_id, {
        "type": "cancel_requested",
        "message": reason,
    })
    return {"run_id": run_id, "status": "cancel_requested"}


@app.get("/api/runs/{run_id}/stream")
async def api_stream_run(run_id: str):
    """Server-Sent Events stream for live run progress."""
    async def event_generator():
        sent = 0
        while True:
            event_list = events.get_events(run_id)
            while sent < len(event_list):
                ev = event_list[sent]
                yield f"data: {json.dumps(ev)}\n\n"
                sent += 1
            if events.is_done(run_id):
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/screenshot/{run_id}/{filename:path}")
async def screenshot(run_id: str, filename: str, request: Request):
    """Retrieve a screenshot by run_id and filename."""
    image_data = await screenshots.get_screenshot(run_id, filename)
    return StreamingResponse(io.BytesIO(image_data), media_type="image/png")


@app.get("/")
async def root():
    return {"status": "StorySpec AI API is running."}


def _execute_run(run_id: str, url: str, story: str, headless: bool):
    """Run the agentic pipeline and push SSE events."""
    from story_spec.core import runner

    def on_progress(rid, i, total, step, result):
        path = result.screenshot_path
        screenshot_val = path if path and path.startswith("http") else (Path(path).name if path else None)
        events.push_event(rid, {
            "type": "step",
            "step_index": i,
            "action": step.action.value,
            "description": step.description,
            "status": result.status.value,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "screenshot": screenshot_val,
        })

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        completed = loop.run_until_complete(
            runner.execute(
                url,
                story,
                headless=headless,
                on_progress=on_progress,
                run_id=run_id,
                should_cancel=lambda: events.should_cancel(run_id),
            )
        )
        events.push_event(run_id, {
            "type": "finished",
            "overall_status": completed.overall_status.value,
            "passed": completed.passed,
            "failed": completed.failed,
            "total_duration_ms": completed.total_duration_ms,
            "goal_achieved": completed.goal_achieved,
            "canceled": completed.canceled,
            "cancel_reason": completed.cancel_reason,
            "summary": completed.summary,
        })
    except Exception as exc:
        events.push_event(run_id, {"type": "error", "message": str(exc)})
    finally:
        events.mark_done(run_id)
        events.cleanup(run_id)


def start():
    import uvicorn
    
    # Initialize LangSmith tracing
    setup_langsmith()
    
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
