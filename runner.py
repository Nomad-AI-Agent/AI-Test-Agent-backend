import asyncio
import uuid
import time
from typing import Optional, Callable
from models import TestRun, StepResult, TestStep, StepStatus
import storage
import parser_agent, browser_agent, report_agent


ProgressCallback = Callable[[str, int, int, TestStep, StepResult], None]


def create_run(url: str, story: str) -> TestRun:
    return TestRun(
        id=str(uuid.uuid4())[:8],
        url=url,
        story=story,
    )


async def execute(
    url: str,
    story: str,
    headless: bool = True,
    on_progress: Optional[ProgressCallback] = None,
) -> TestRun:
    """Full pipeline: parse → execute → summarize → save."""

    run = create_run(url, story)
    storage.save_run(run)

    run.steps = parser_agent.parse_story(url, story)
    storage.save_run(run)

    def _progress(i: int, step: TestStep, result: StepResult):
        if on_progress:
            on_progress(run.id, i, len(run.steps), step, result)

    run.results = await browser_agent.run_steps(run, on_progress=_progress, headless=headless)
    storage.save_run(run)

    run.summary = report_agent.generate_summary(run)
    storage.save_run(run)

    return run
