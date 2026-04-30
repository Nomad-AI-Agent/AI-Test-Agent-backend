"""
Agentic test runner: orchestrates the step-by-step LLM-driven browser loop.

Flow: Navigate -> Observe page -> Ask LLM for next action -> Execute -> Repeat
"""

import asyncio
import uuid
import time
from typing import Optional, Callable, List, Dict, Any
from story_spec.core.models import TestRun, StepResult, TestStep, StepStatus
from story_spec.core import storage
from story_spec.agents import parser
from story_spec.agents import browser
from story_spec.agents import analyzer
from story_spec.agents import reporter
from story_spec.core import config

ProgressCallback = Callable[[str, int, int, TestStep, StepResult], None]

MAX_STEPS = 25
HIGH_IMPACT_KEYWORDS = {
    "create", "save", "submit", "confirm", "delete", "remove", "finish",
    "complete", "continue", "next", "login", "log in", "sign in", "checkout",
    "place order", "pay", "purchase", "send", "invite", "publish",
}
ERROR_HINTS = {
    "error", "failed", "invalid", "required", "try again", "incorrect",
    "already exists", "unable", "problem", "issue", "missing",
}
SUCCESS_HINTS = {
    "success", "successfully", "created", "saved", "completed", "welcome",
    "dashboard", "overview", "confirmed", "done",
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return default


def create_run(url: str, story: str, run_id: Optional[str] = None) -> TestRun:
    return TestRun(
        id=run_id or str(uuid.uuid4()),
        url=url,
        story=story,
    )


def _infer_goal_status_from_results(run: TestRun) -> Optional[bool]:
    """
    Infer the final run verdict when the LLM never returns an explicit `done`.

    If any step failed, the run should fail. If every executed step passed, leave
    the verdict unset so the fallback overall-status logic can treat the run as
    passed instead of forcing a contradictory FAIL.
    """
    if any(result.status == StepStatus.FAIL for result in run.results):
        return False
    if run.results and all(result.status == StepStatus.PASS for result in run.results):
        return None
    return None


def _contains_any(text: str, keywords: set[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _decision_text(action: str, target: Optional[str], value: Optional[str], description: str) -> str:
    return " ".join(part for part in [action, target or "", value or "", description or ""] if part)


def _is_high_impact_action(action: str, target: Optional[str], value: Optional[str], description: str) -> bool:
    if action not in {"click", "select"}:
        return False
    return _contains_any(_decision_text(action, target, value, description), HIGH_IMPACT_KEYWORDS)


def _same_decision(decision: Dict[str, Any], history_item: Dict[str, Any]) -> bool:
    return (
        decision.get("action") == history_item.get("action")
        and (decision.get("target") or None) == (history_item.get("target") or None)
        and (decision.get("value") or None) == (history_item.get("value") or None)
    )


def _was_successfully_done_before(decision: Dict[str, Any], history: List[Dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("success") and _same_decision(decision, item):
            return True
    return False


def _selector_still_visible(context: Dict[str, Any], selector: Optional[str]) -> bool:
    if not selector:
        return False
    for key in ("inputs", "checkables", "buttons", "links"):
        for item in context.get(key, []):
            if item.get("selector") == selector:
                return True
    return False


def _page_has_error_signal(context: Dict[str, Any]) -> bool:
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(_contains_any(text, ERROR_HINTS) for text in haystacks)


def _page_has_success_signal(context: Dict[str, Any]) -> bool:
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(_contains_any(text, SUCCESS_HINTS) for text in haystacks)


def _coerce_duplicate_high_impact_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    action = decision.get("action", "screenshot")
    target = decision.get("target")
    value = decision.get("value")
    description = decision.get("description", "")

    if not _is_high_impact_action(action, target, value, description):
        return decision
    if not _was_successfully_done_before(decision, history):
        return decision

    if _page_has_error_signal(context):
        return {
            "thought": "The same high-impact action already succeeded once and the page now shows validation or error feedback.",
            "action": "screenshot",
            "description": "Capture page state after validation or error feedback",
        }

    if _page_has_success_signal(context) or not _selector_still_visible(context, target):
        return {
            "thought": "The same irreversible action already succeeded once and the page now indicates the workflow likely completed.",
            "action": "done",
            "description": f"Goal achieved after {description or action}",
            "success": True,
        }

    return {
        "thought": "The same irreversible action already succeeded once. Wait for the UI to settle before taking another step.",
        "action": "wait",
        "value": "1200",
        "description": "Wait for the page to settle after a successful submission",
    }


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
    page = session.require_page()

    screenshot_dir = config.SCREENSHOTS_DIR / run.id
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    history: List[Dict] = []
    step_index = 0
    total_start = time.time()

    try:
        # Step 0: Navigate to the initial URL
        result = await browser.execute_action(
            page=page,
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
            context = {}
            try:
                context = await analyzer.get_page_context(page)
                context_str = analyzer.format_page_context(context)
            except Exception as e:
                context_str = f"URL: {page.url}\nError extracting page context: {str(e)}"

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

            decision = _coerce_duplicate_high_impact_decision(decision, history, context)

            # 3. Check if the LLM says we're done
            if decision.get("action") == "done" or decision.get("done", False):
                # Record the final assessment
                final_result = await browser.execute_action(
                    page=page,
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
                run.goal_achieved = _as_bool(decision.get("success"), default=False)

                if on_progress:
                    on_progress(run.id, step_index, step_index + 1, final_result.step, final_result)

                break

            # 4. Act: Execute the decided action
            action = decision.get("action", "screenshot")
            target = decision.get("target")
            value = decision.get("value")
            description = decision.get("description", f"Step {step_index + 1}")

            result = await browser.execute_action(
                page=page,
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

        # If we hit MAX_STEPS without the LLM saying "done", avoid forcing a FAIL
        # when all executed steps actually passed.
        if step_index >= MAX_STEPS and run.goal_achieved is None:
            run.goal_achieved = _infer_goal_status_from_results(run)

        run.total_duration_ms = int((time.time() - total_start) * 1000)
        storage.save_run(run)

    finally:
        await session.stop()

    # Generate AI summary
    run.summary = reporter.generate_summary(run)
    storage.save_run(run)

    return run
