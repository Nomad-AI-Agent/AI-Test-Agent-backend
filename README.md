# AI Test Agent

An AI-powered user story testing agent. Provide a natural language user story and a base URL, and the agent uses Groq to parse your story into actionable UI tests, executes them automatically using Playwright, captures screenshots, and generates a visual summary test report.

## Getting Started

### Requirements
- Python 3+

### Setup Instructions

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   
   # Windows (PowerShell):
   .\.venv\Scripts\activate
   
   # macOS/Linux:
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright Browsers:**
   Playwright requires underlying browser binaries to run tests. After installing it via pip, you must run its browser installation command.
   ```bash
   playwright install
   ```

4. **Set your Groq API Key:**
   The agent loads configuration from a `.env` file. 
   - Open `.env` and set your `GROQ_API_KEY`.

   If you prefer using environment variables directly:
   ```bash
   # Windows (PowerShell):
   $env:GROQ_API_KEY="your_api_key_here"
   
   # macOS/Linux:
   export GROQ_API_KEY="your_api_key_here"
   ```

## Usage

### Run a User Story Test
You can use the CLI tool to directly run a test.

```bash
python cli.py run --url "https://facebook.com" --story "User visits the homepage and sees the main heading"
```

**Options:**
- `--url` / `-u`: The URL to verify and test.
- `--story` / `-s`: The user story written in plain English.
- `--no-headless`: Opens the browser visibly so you can watch as Playwright clicks and types through the page.
- `--no-dashboard`: Prevents the local dashboard from automatically populating after a generated test concludes.

### View Historical Runs
To view the output summary and all saved screenshots from past testing runs, you can launch the local database web server.

```bash
python cli.py dashboard
```
*(Runs locally on `http://127.0.0.1:7788` unless altered)*
