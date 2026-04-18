# StorySpec AI — Quiet Intelligence

An AI-powered user story testing agent. Provide a natural language user story and a base URL, and the agent uses LLMs (via Groq) to parse your story into actionable UI tests, executes them automatically using Playwright, captures screenshots, and generates a visual summary test report.

## Features
- **Agentic Loop**: Dynamic navigation and element discovery.
- **Natural Language Parsing**: Write tests in plain English.
- **PostgreSQL Storage**: Robust history and results persistence.
- **Modern Packaging**: Structured as a modular Python package.

## Getting Started

### Requirements
- Python 3.10+
- **PostgreSQL Database**: A running instance (local or remote).
- **Groq API Key**: Needed for the agent "brain" and report generation.

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
   GROQ_API_KEY=your_groq_key_here
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

## Project Structure

The project has been refactored into a structured package:

- `src/story_spec/`
  - `agents/`: AI logic for browser control, analysis, and reporting.
  - `api/`: FastAPI implementation for the dashboard backend.
  - `core/`: Foundational models, storage logic, and configuration.
- `cli.py`: Root entry point for CLI and dashboard launcher.
- `main.py`: Root entry point for the API backend server.
- `screenshots/`: Local directory where run screenshots are persisted.
