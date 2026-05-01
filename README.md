# Nomad AI Agent

An AI-powered user story testing agent. Provide a natural language user story and a base URL, and the agent uses LLMs (via OpenRouter) to parse your story into actionable UI tests, executes them automatically using Playwright, captures screenshots, and generates a visual summary test report.

## Features
- **Agentic Loop**: Dynamic navigation and element discovery.
- **Natural Language Parsing**: Write tests in plain English.
- **PostgreSQL Storage**: Robust history and results persistence.
- **Modern Packaging**: Structured as a modular Python package.

## Getting Started

### Requirements
- Python 3.10+
- **PostgreSQL Database**: A running instance (local or remote).
- **OpenRouter API Key**: Needed for the agent "brain" and report generation.

### Setup Instructions

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   
   # Windows:
   .\.venv\Scripts\activate
   
   # macOS/Linux:
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the root directory (or update the existing one):
   ```env
   OPENROUTER_API_KEY=your_openrouter_key_here
   OPENROUTER_MODEL=openrouter/auto
   DATABASE_URL=postgres://user:password@localhost:5432/dbname
   ```

## Usage

### Run a User Story Test
You can use the CLI tool to directly run a test.

```bash
python cli.py run --url "https://github.com" --story "User visits the landing page and clicks the Sign Up button"
```

**Options:**
- `--url` / `-u`: The URL to verify and test.
- `--story` / `-s`: The user story written in plain English.
- `--no-headless`: Opens the browser visibly so you can watch as Playwright clicks and types through the page.
- `--no-dashboard`: Prevents the local dashboard from automatically populating after a generated test concludes.

### Start the API Server
The backend API (used by the Next.js UI) can be started via the root entry point:

```bash
python main.py
```

Alternatively, you can launch it via the CLI:
```bash
python cli.py dashboard
```
*(Runs locally on `http://127.0.0.1:7788` unless configured otherwise)*

## API Documentation

Base URL:

```text
http://127.0.0.1:7788
```

### `GET /`

Health check endpoint.

Example response:

```json
{
  "status": "StorySpec AI API is running."
}
```

### `GET /api/runs`

Returns all stored test runs in reverse chronological order.

### `GET /api/runs/{run_id}`

Returns one stored run, including:
- run metadata
- overall status
- cancellation state
- step-by-step results
- screenshot file names or URLs
- timestamps in multiple formats for client compatibility
- internally store run creation as a Python `datetime` object and persist it as a timezone-aware timestamp

### `POST /api/runs`

Starts a new test run asynchronously.

Request body:

```json
{
  "url": "https://example.com",
  "story": "User visits the page and signs in",
  "headless": true
}
```

Example response:

```json
{
  "run_id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4"
}
```

Run timestamps in API responses:

- `created_at`: Unix timestamp in milliseconds
- `created_at_seconds`: Unix timestamp in seconds
- `created_at_iso`: ISO 8601 UTC timestamp

Internally, `created_at` is now a simple timezone-aware Python `datetime` value; using a datetime type is clearer and avoids raw epoch float drift or ambiguity.

### `POST /api/runs/{run_id}/cancel`

Requests cancellation of an in-progress run.

The run keeps all steps that were already completed and is persisted with:
- `overall_status: "canceled"`
- `canceled: true`
- `cancel_reason`

Request body:

```json
{
  "reason": "Stopped by user from dashboard"
}
```

Example response while the run is still active:

```json
{
  "run_id": "8f1f2c10-6a50-4c22-b1b7-7d37e2b0a7f4",
  "status": "cancel_requested"
}
```

### `GET /api/runs/{run_id}/stream`

Server-Sent Events endpoint for live run updates.

Typical event types:
- `step`
- `cancel_requested`
- `finished`
- `error`
- final stream terminator event: `done`

### `GET /screenshot/{run_id}/{filename}`

Returns a screenshot image for a run step.

This endpoint supports:
- locally stored screenshots
- Supabase-backed screenshots

### Run Object Notes

Run responses now include these cancellation-related fields:

```json
{
  "created_at": 1714512345678,
  "created_at_seconds": 1714512345.678,
  "created_at_iso": "2026-04-30T18:05:45.678000+00:00",
  "overall_status": "canceled",
  "canceled": true,
  "cancel_reason": "Stopped by user from dashboard"
}
```

## Project Structure

The project has been refactored into a structured package:

- `src/story_spec/`
  - `agents/`: AI logic for browser control, analysis, and reporting.
  - `api/`: FastAPI implementation for the dashboard backend.
  - `core/`: Foundational models, storage logic, and configuration.
- `cli.py`: Root entry point for CLI and dashboard launcher.
- `main.py`: Root entry point for the API backend server.
- `screenshots/`: Local directory where run screenshots are persisted.
