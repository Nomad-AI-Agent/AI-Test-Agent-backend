import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
import storage
import config

app = FastAPI(title="Story Tester Dashboard")

templates_dir = Path(__file__).parent
env = Environment(loader=FileSystemLoader(str(templates_dir)))


def basename_filter(path):
    return Path(path).name if path else ""


env.filters["basename"] = basename_filter


@app.get("/", response_class=HTMLResponse)
async def index():
    runs = storage.list_runs()
    tpl = env.get_template("index.html")
    return tpl.render(runs=runs)


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: str):
    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    tpl = env.get_template("run.html")
    return tpl.render(run=run)


@app.get("/screenshot/{run_id}/{filename}")
async def screenshot(run_id: str, filename: str):
    path = config.SCREENSHOTS_DIR / run_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(str(path), media_type="image/png")


def start():
    import uvicorn
    uvicorn.run(app, host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, log_level="warning")
