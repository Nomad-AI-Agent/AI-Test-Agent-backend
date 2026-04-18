"""
Agentic test runner: orchestrates the step-by-step LLM-driven browser loop.

Flow: Navigate -> Observe page -> Ask LLM for next action -> Execute -> Repeat
"""

import asyncio
import uuid
import time
from typing import Optional, Callable, List, Dict
from story_spec.core.models import TestRun, StepResult, TestStep, StepStatus
from story_spec.core import storage
from story_spec.agents import parser
from story_spec.agents import browser
from story_spec.agents import analyzer
from story_spec.agents import reporter
from story_spec.core import config

ProgressCallback = Callable[[str, int, int, TestStep, StepResult], None]

MAX_STEPS = 25


def create_run(url: str, story: str, run_id: Optional[str] = None) -> TestRun:
    return TestRun(
        id=run_id or str(uuid.uuid4())[:8],
        url=url,
        story=story,
    )


async def execute(
    url: str,
    story: str,
    headless: bool = True,
    on_progress: Optional[ProgressCallback] = None,
    run_id: Optional[str] = None,
) -> TestRun:
    """Full agentic pipeline: navigate -> observe -> decide -> act -> repeat."""

    run = create_run(url, story, run_id)
    storage.save_run(run)

    session = browser.BrowserSession(headless=headless)
    await session.start()

    screenshot_dir = config.SCREENSHOTS_DIR / run.id
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    history: List[Dict] = []
    step_index = 0
    total_start = time.time()

    try:
        # Step 0: Navigate to the initial URL
        result = await browser.execute_action(
            page=session.page,
            action="navigate",
            target=url,
            value=None,
            description=f"Navigate to {url}",
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )

        run.steps.append(result.step)
        run.results.append(result)
        history.append({
            "action": "navigate",
            "description": f"Navigate to {url}",
            "success": result.status == StepStatus.PASS,
            "error": result.error,
        })

        if on_progress:
            on_progress(run.id, step_index, MAX_STEPS, result.step, result)

        step_index += 1

        # Agentic loop
        consecutive_failures = 0
        max_consecutive_failures = 3

        while step_index < MAX_STEPS:
            # 1. Observe: Extract current page context
            try:
                context = await analyzer.get_page_context(session.page)
                context_str = analyzer.format_page_context(context)
            except Exception as e:
                context_str = f"URL: {session.page.url}\nError extracting page context: {str(e)}"

            # 2. Think: Ask LLM what to do next
            last_error = None
            if run.results and run.results[-1].status == StepStatus.FAIL:
                last_error = run.results[-1].error

            try:
                decision = parser.decide_next_action(
                    goal=story,
                    page_context_str=context_str,
                    history=history,
                    error_context=last_error,
                )
            except Exception as e:
                # LLM call failed — take a screenshot and continue
                decision = {
                    "thought": f"LLM error: {str(e)}",
                    "action": "screenshot",
                    "description": "Screenshot (LLM call failed)",
                }

            # 3. Check if the LLM says we're done
            if decision.get("action") == "done" or decision.get("done", False):
                # Record the final assessment
                final_result = await browser.execute_action(
                    page=session.page,
                    action="done",
                    target=None,
                    value=None,
                    description=decision.get("description", "Goal assessment complete"),
                    screenshot_dir=screenshot_dir,
                    step_index=step_index,
                )
                run.steps.append(final_result.step)
                run.results.append(final_result)

                # Set the agent's verdict on goal achievement
                run.goal_achieved = decision.get("success", False)

                if on_progress:
                    on_progress(run.id, step_index, step_index + 1, final_result.step, final_result)

                break

            # 4. Act: Execute the decided action
            action = decision.get("action", "screenshot")
            target = decision.get("target")
            value = decision.get("value")
            description = decision.get("description", f"Step {step_index + 1}")

            result = await browser.execute_action(
                page=session.page,
                action=action,
                target=target,
                value=value,
                description=description,
                screenshot_dir=screenshot_dir,
                step_index=step_index,
            )

            run.steps.append(result.step)
            run.results.append(result)
            history.append({
                "action": action,
                "target": target,
                "value": value,
                "description": description,
                "success": result.status == StepStatus.PASS,
                "error": result.error,
            })

            if on_progress:
                on_progress(run.id, step_index, MAX_STEPS, result.step, result)

            # Track consecutive failures to avoid infinite failing loops
            if result.status == StepStatus.FAIL:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    run.goal_achieved = False
                    break
            else:
                consecutive_failures = 0

            step_index += 1

            # Small delay between steps to let pages settle
            await asyncio.sleep(0.3)

        # If we hit MAX_STEPS without the LLM saying "done"
        if step_index >= MAX_STEPS and run.goal_achieved is None:
            run.goal_achieved = False

        run.total_duration_ms = int((time.time() - total_start) * 1000)
        storage.save_run(run)

    finally:
        await session.stop()

    # Generate AI summary
    run.summary = reporter.generate_summary(run)
    storage.save_run(run)

    return run
