# StorySpec AI — API Documentation

AI-powered user story testing agent. Takes natural language user stories, executes them via Playwright, captures screenshots and video, and generates a summary report.

Base URL: `http://127.0.0.1:7788`

---

## Table of Contents

- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
  - [Health Check](#get-)
  - [List Runs](#get-apiruns)
  - [Get Run](#get-apirunsrun_id)
  - [Create Run](#post-apiruns)
  - [Cancel Run](#post-apirunsrun_idcancel)
  - [Pause Run](#post-apirunsrun_idpause)
  - [Resume Run](#post-apirunsrun_idresume)
  - [Stream Events](#get-apirunsrun_idstream)
  - [Get Screenshot](#get-screenshotrun_idfilename)
  - [Get Video](#get-videorun_id)
- [Run Object Reference](#run-object-reference)
- [Environment Variables](#environment-variables)
- [Project Structure](#project-structure)

---

## Quick Start

```bash
# Install
pip install -r requirements.txt
playwright install

# Configure
cp .env.example .env
# Edit .env with your OPENROUTER_API_KEY and DATABASE_URL

# Run a test via CLI
python cli.py run --url "https://github.com" --story "User clicks Sign Up"

# Start the API server
python main.py
```

---

## Authentication

Currently the API does not require authentication for run endpoints. Set `OPENROUTER_API_KEY` in `.env` for LLM functionality.

---

## Endpoints

### `GET /`

Health check.

**Response `200`:**

```json
{
  "status": "StorySpec AI API is running."
}
```

---

### `GET /api/runs`

Returns all stored test runs in reverse chronological order.

**Response `200`:** Array of [Run Objects](#run-object-reference).

---

### `GET /api/runs/{run_id}`

Returns a specific test run with full step details.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `run_id` | string | UUID of the run |

**Response `200`:** [Run Object](#run-object-reference)

**Response `404`:**
```json
{ "detail": "Run not found" }
```

---

### `POST /api/runs`

Starts a new test run asynchronously. Returns immediately with the `run_id`; stream progress via [`GET /api/runs/{run_id}/stream`](#get-apirunsrun_idstream).

**Request body:**

```json
{
  "url": "https://example.com",
  "story": "User visits the page and signs in",
  "headless": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | — | Target URL to test (required) |
| `story` | string | — | Natural language user story (required) |
| `headless` | boolean | `true` | Run browser in headless mode |

**Response `201`:**

```json
{
  "run_id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4"
}
```

---

### `POST /api/runs/{run_id}/cancel`

Requests cancellation of a run in progress. Already-completed steps are preserved.

**Request body:**

```json
{
  "reason": "Stopped by user from dashboard"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reason` | string | `"Run canceled by user."` | Reason for cancellation |

**Response `200`:**

```json
{
  "run_id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4",
  "status": "cancel_requested"
}
```

---

### `POST /api/runs/{run_id}/pause`

Pauses a running test. The session state (cookies, localStorage, page URL, history) is saved as a checkpoint for later resume.

**Request body:**

```json
{
  "reason": "Paused for review"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reason` | string | `"Run paused by user."` | Reason for pausing |

**Response `200`:**

```json
{
  "run_id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4",
  "status": "pause_requested"
}
```

---

### `POST /api/runs/{run_id}/resume`

Resumes a paused run from its saved checkpoint. A new Playwright session is started and the saved cookies, localStorage, and page URL are restored.

**Response `200`:**

```json
{
  "run_id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4",
  "status": "resumed"
}
```

**Response `400`** (not paused or no checkpoint):

```json
{
  "run_id": "...",
  "status": "pending",
  "message": "Run is not paused or has no checkpoint"
}
```

---

### `GET /api/runs/{run_id}/stream`

Server-Sent Events (SSE) endpoint for live progress updates.

**Event types:**

| Event | `type` value | Description |
|-------|-------------|-------------|
| Step completed | `"step"` | Emitted after each browser action |
| Cancel requested | `"cancel_requested"` | User requested cancellation |
| Pause requested | `"pause_requested"` | User requested pause |
| Paused | `"paused"` | Run has been paused (includes checkpoint) |
| Resumed | `"resumed"` | Run has been resumed |
| Finished | `"finished"` | Run completed (success, failure, or canceled) |
| Error | `"error"` | An error occurred during execution |
| Stream end | `"done"` | Final event signaling stream closure |

**`"step"` event payload:**

```json
{
  "type": "step",
  "step_index": 0,
  "action": "navigate",
  "description": "Navigate to https://example.com",
  "status": "pass",
  "error": null,
  "duration_ms": 2400,
  "screenshot": "step_00.png"
}
```

**`"finished"` event payload:**

```json
{
  "type": "finished",
  "overall_status": "pass",
  "passed": 5,
  "failed": 0,
  "total_duration_ms": 45000,
  "goal_achieved": true,
  "canceled": false,
  "cancel_reason": null,
  "paused": false,
  "summary": "The test successfully logged in...",
  "video_url": "/video/8f1f2c10..."
}
```

**`"paused"` event payload:**

```json
{
  "type": "paused",
  "message": "Paused for review",
  "checkpoint": { "...": "..." }
}
```

---

### `GET /screenshot/{run_id}/{filename}`

Returns a step screenshot image.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `run_id` | string | UUID of the run |
| `filename` | string | Screenshot filename (e.g. `step_00.png`) |

**Response `200`:** PNG image (`image/png`)

**Response `404`:**
```json
{ "detail": "Screenshot not found" }
```

Supports both locally stored and Supabase-backed screenshots.

---

### `GET /video/{run_id}`

Returns the recorded WebM video of the full run.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `run_id` | string | UUID of the run |

**Response `200`:** WebM video (`video/webm`) — either served directly or redirected to Supabase URL

**Response `404`:**
```json
{ "detail": "Video not found" }
```

Video recording is enabled automatically for all runs. The video is uploaded to the Supabase bucket configured by `SUPABASE_VIDEO_BUCKET` (default: `"videos"`), falling back to local storage.

---

## Run Object Reference

Returned by `GET /api/runs` and `GET /api/runs/{run_id}`.

```json
{
  "id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4",
  "url": "https://example.com",
  "story": "User visits the page and signs in",
  "created_at": 1714512345678,
  "created_at_seconds": 1714512345.678,
  "created_at_iso": "2026-04-30T18:05:45.678000+00:00",
  "overall_status": "pass",
  "goal_achieved": true,
  "canceled": false,
  "cancel_reason": null,
  "paused": false,
  "passed": 5,
  "failed": 0,
  "total_duration_ms": 45000,
  "summary": "The agent successfully logged in and verified the dashboard...",
  "video_url": "/video/8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4",
  "steps": [
    {
      "index": 0,
      "action": "navigate",
      "description": "Navigate to https://example.com",
      "target": "https://example.com",
      "value": null,
      "status": "pass",
      "error": null,
      "duration_ms": 2400,
      "screenshot": "step_00.png"
    }
  ]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | UUID of the run |
| `url` | string | The target URL tested |
| `story` | string | The user story description |
| `created_at` | number | Unix timestamp in milliseconds |
| `created_at_seconds` | number | Unix timestamp in seconds |
| `created_at_iso` | string | ISO 8601 UTC timestamp |
| `overall_status` | string | One of: `pending`, `pass`, `fail`, `canceled`, `paused` |
| `goal_achieved` | boolean or null | Final verdict from the agent |
| `canceled` | boolean | Whether the run was canceled |
| `cancel_reason` | string or null | Reason for cancellation |
| `paused` | boolean | Whether the run is paused |
| `passed` | number | Number of passed steps |
| `failed` | number | Number of failed steps |
| `total_duration_ms` | number | Total execution time in milliseconds |
| `summary` | string or null | AI-generated summary of the run |
| `video_url` | string or null | URL to the recorded run video |
| `steps` | array | Array of step objects (see below) |

### Step Object

| Field | Type | Description |
|-------|------|-------------|
| `index` | number | Step position (0-based) |
| `action` | string | One of: `navigate`, `click`, `type`, `select`, `scroll`, `hover`, `wait`, `screenshot`, `done` |
| `description` | string | Human-readable step description |
| `target` | string or null | CSS selector or URL |
| `value` | string or null | Text to type, option to select, etc. |
| `status` | string | One of: `pending`, `pass`, `fail`, `skip`, `canceled`, `paused` |
| `error` | string or null | Error message if the step failed |
| `duration_ms` | number | Step execution time in milliseconds |
| `screenshot` | string or null | Screenshot filename or URL |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | Yes | — | API key for OpenRouter LLM |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `SUPABASE_URL` | No | — | Supabase project URL (for screenshot/video storage) |
| `SUPABASE_KEY` | No | — | Supabase service key |
| `SUPABASE_BUCKET` | No | `screenshots` | Supabase bucket for screenshots |
| `SUPABASE_VIDEO_BUCKET` | No | `videos` | Supabase bucket for recorded videos |
| `OPENROUTER_MODEL` | No | `openrouter/auto` | LLM model to use |
| `JWT_SECRET_KEY` | No | — | Secret key for JWT auth |
| `ENVIRONMENT` | No | `development` | App environment (`development` / `production`) |
| `HOST` | No | `127.0.0.1` | API server bind address |
| `PORT` | No | `7788` | API server port |

---

## Project Structure

```
├── main.py                          # API server entry point
├── cli.py                           # CLI entry point (run, dashboard, serve, runs)
├── requirements.txt                 # Dependencies
├── Dockerfile                       # Docker build for Railway deployment
├── Procfile                         # Heroku/Railway process file
├── .env.example                     # Environment variable template
├── screenshots/                     # Local screenshot storage (gitignored)
├── videos/                          # Local video storage (gitignored)
├── scripts/                         # Utility scripts
└── src/story_spec/
    ├── agents/
    │   ├── browser.py               # Playwright session & action execution
    │   ├── analyzer.py              # DOM / page context extraction
    │   ├── parser.py                # LLM next-action decision engine
    │   └── reporter.py              # LLM test run summary generation
    ├── api/
    │   └── server.py                # FastAPI server (REST + SSE)
    ├── core/
    │   ├── config.py                # Pydantic settings from env vars
    │   ├── models.py                # Dataclasses: TestRun, TestStep, StepResult
    │   ├── runner.py                # Agentic LangGraph loop (core engine)
    │   ├── storage.py               # PostgreSQL persistence
    │   ├── supabase.py              # Supabase storage for screenshots & video
    │   └── tracing.py               # LangSmith tracing
    └── db/
        ├── models.py                # SQLAlchemy ORM models
        ├── session.py               # SQLAlchemy engine & session
        └── migrations/              # Alembic migration files
```
