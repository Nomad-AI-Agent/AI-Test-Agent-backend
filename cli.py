#!/usr/bin/env python3
#!/usr/bin/env python3
import sys
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import click
from models import StepStatus

PASS_COLOR = "green"
FAIL_COLOR = "red"
SKIP_COLOR = "yellow"
INFO_COLOR = "cyan"


def status_color(status: StepStatus) -> str:
    if status == StepStatus.PASS:
        return PASS_COLOR
    if status == StepStatus.FAIL:
        return FAIL_COLOR
    return SKIP_COLOR


@click.group()
def cli():
    """story-tester — AI-powered user story testing agent"""
    pass


@cli.command()
@click.option("--url", "-u", required=True, help="URL to test against")
@click.option("--story", "-s", required=True, help="User story in plain English")
@click.option("--headless/--no-headless", default=True, help="Run browser in headless mode")
@click.option("--no-dashboard", is_flag=True, default=False, help="Skip opening dashboard after run")
def run(url, story, headless, no_dashboard):
    """Run a user story test against a URL."""

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        click.echo(click.style("ERROR: LLM_API_KEY environment variable not set.", fg="red"))
        click.echo("  Please set it in a .env file or export it:")
        click.echo("  GROQ_API_KEY=your_key_here")
        sys.exit(1)

    click.echo()
    click.echo(click.style("  story-tester (agentic mode)", fg=INFO_COLOR, bold=True))
    click.echo(click.style("  " + "-" * 50, fg="bright_black"))
    click.echo(f"  URL   : {url}")
    click.echo(f"  Story : {story}")
    click.echo(click.style("  " + "-" * 50, fg="bright_black"))
    click.echo()

    click.echo(click.style("  [1/2] Running agentic browser test...", fg=INFO_COLOR))
    click.echo()

    from runner import execute

    first_progress = [True]

    def on_progress(run_id, i, total, step, result):
        icon = "+" if result.status == StepStatus.PASS else ("x" if result.status == StepStatus.FAIL else "-")
        color = status_color(result.status)
        step_num = f"#{i+1:02d}"
        action = step.action.value.upper()
        desc = step.description[:55] + "..." if len(step.description) > 55 else step.description

        click.echo(
            f"  {click.style(icon, fg=color, bold=True)}  "
            f"{click.style(step_num, fg='bright_black')}  "
            f"{click.style(f'{action:15}', fg='bright_black')}  "
            f"{desc}"
            + (f"  {click.style(result.error[:40], fg='red')}" if result.error else "")
        )

    completed_run = asyncio.run(execute(url, story, headless=headless, on_progress=on_progress))

    # Step 3: Summary
    click.echo()
    click.echo(click.style("  [2/2] Generating AI summary...", fg=INFO_COLOR))
    click.echo()
    click.echo(click.style("  " + "-" * 50, fg="bright_black"))

    overall = completed_run.overall_status
    overall_color = status_color(overall)
    click.echo(
        f"  Result  : {click.style(overall.value.upper(), fg=overall_color, bold=True)}"
        f"  ({completed_run.passed} passed, {completed_run.failed} failed)"
        f"  {completed_run.total_duration_ms}ms"
    )
    click.echo(f"  Run ID  : #{completed_run.id}")
    click.echo()

    if completed_run.summary:
        for line in completed_run.summary.split("\n"):
            click.echo(f"  {line}")
        click.echo()

    click.echo(click.style("  " + "-" * 50, fg="bright_black"))

    import config
    ui_url = f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}"
    click.echo(f"  Dashboard : {click.style(ui_url, fg=INFO_COLOR)}")
    click.echo()

    if not no_dashboard:
        click.echo(click.style("  Starting UI server...", fg="bright_black"))
        import threading
        from server import start as start_server
        t = threading.Thread(target=start_server, daemon=True)
        t.start()
        import webbrowser, time
        time.sleep(1.5)
        webbrowser.open(ui_url)
        click.echo(click.style(f"  Serving at {ui_url}  (Ctrl+C to stop)", fg="bright_black"))
        click.echo()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo()
            click.echo("  Stopped.")


@cli.command()
def dashboard():
    """Start the UI server and open it in your browser."""
    import config, webbrowser, threading, time
    url = f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}"
    click.echo(click.style(f"\n  Quiet Intelligence UI → {url}\n", fg=INFO_COLOR))
    from server import start as start_server
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(1.5)
    webbrowser.open(url)
    click.echo(click.style(f"  Serving at {url}  (Ctrl+C to stop)\n", fg="bright_black"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n  Stopped.")


@cli.command()
def serve():
    """Alias for `dashboard` — start the UI server."""
    import config, webbrowser, threading, time
    url = f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}"
    click.echo(click.style(f"\n  Quiet Intelligence UI → {url}\n", fg=INFO_COLOR))
    from server import start as start_server
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(1.5)
    webbrowser.open(url)
    click.echo(click.style(f"  Serving at {url}  (Ctrl+C to stop)\n", fg="bright_black"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n  Stopped.")


@cli.command()
def runs():
    """List all past test runs."""
    import storage
    all_runs = storage.list_runs()
    if not all_runs:
        click.echo("  No runs yet.")
        return
    click.echo()
    for r in all_runs:
        color = PASS_COLOR if r.overall_status == StepStatus.PASS else FAIL_COLOR
        click.echo(
            f"  {click.style('#' + r.id, fg='cyan')}  "
            f"{click.style(r.overall_status.value.upper(), fg=color, bold=True):8}  "
            f"{r.passed}p/{r.failed}f  "
            f"{r.story[:60]}"
        )
    click.echo()


if __name__ == "__main__":
    cli()
