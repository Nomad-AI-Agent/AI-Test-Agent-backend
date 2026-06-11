"""
LangGraph-based autonomous browser testing agent.

Architecture:
- Observe: Extract page context
- Reason: LLM decides next action
- Safety: Apply guardrails/coercion
- Action: Execute browser action
- Evaluate: Check termination conditions
- Done: Finalize and return results

LangSmith tracing is enabled automatically when the following env vars are set:
    LANGCHAIN_API_KEY=<your key>
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_PROJECT=<your project name>
"""

import asyncio
import time
from typing import Optional, Callable
from pathlib import Path
from datetime import datetime

# LangSmith tracing
try:
    from langsmith import traceable
    LANGSMITH_AVAILABLE = True
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(fn):
            return fn
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator
    LANGSMITH_AVAILABLE = False

try:
    from langgraph.graph import StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

from story_spec.core.models import TestRun, StepResult, TestStep, StepStatus, ActionType
from story_spec.core import storage, config
from story_spec.core.state import AgentState
from story_spec.core.runner_utils import as_bool
from story_spec.core.goal_eval import infer_goal_status_from_results
from story_spec.core.nodes import (
    observe_node, reason_node, safety_node, action_node, evaluate_node, done_node,
    route_after_safety, route_after_action,
)
from story_spec.agents import browser, reporter

ProgressCallback = Callable[[str, int, int, TestStep, StepResult], None]
CancelCallback = Callable[[], bool]

MAX_STEPS = 25


def build_graph():
    """Build and compile the LangGraph for autonomous browser testing."""
    try:
        from langgraph.graph import StateGraph
    except Exception as e:
        raise RuntimeError(
            "LangGraph is not installed or failed to import. "
            "Install with: pip install langgraph langchain-core langchain-openai"
        ) from e

    graph = StateGraph(AgentState)

    graph.add_node("observe", observe_node)
    graph.add_node("reason", reason_node)
    graph.add_node("safety", safety_node)
    graph.add_node("action", action_node)
    graph.add_node("evaluate", evaluate_node)

    graph.add_edge("observe", "reason")
    graph.add_edge("reason", "safety")
    graph.add_conditional_edges("safety", route_after_safety, {"done": "done", "action": "action"})
    graph.add_edge("action", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_action, {"observe": "observe", "done": "done"})

    graph.set_entry_point("observe")
    graph.set_finish_point("done")

    return graph.compile()


@traceable(name="agent-execute", run_type="chain")
async def execute(
    url: str,
    story: str,
    headless: bool = True,
    on_progress: Optional[ProgressCallback] = None,
    run_id: Optional[str] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> TestRun:
    """Execute autonomous browser testing for a given URL and story."""
    import uuid

    run = TestRun(
        id=run_id or str(uuid.uuid4()),
        url=url,
        story=story,
    )
    storage.save_run(run)

    session = browser.BrowserSession(headless=headless)
    await session.start()
    page = session.require_page()

    screenshot_dir = config.SCREENSHOTS_DIR / run.id
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    total_start = time.time()

    def cancellation_requested() -> bool:
        return should_cancel() if should_cancel else False

    def cancel_run(reason: str = "Run canceled by user.") -> None:
        run.canceled = True
        run.cancel_reason = reason
        run.goal_achieved = None
        run.total_duration_ms = int((time.time() - total_start) * 1000)
        storage.save_run(run)

    try:
        if cancellation_requested():
            cancel_run()
            return run

        # Step 0: Navigate to initial URL
        nav_result = await browser.execute_action(
            page=page,
            action="navigate",
            target=url,
            value=None,
            description=f"Navigate to {url}",
            screenshot_dir=screenshot_dir,
            step_index=0,
        )

        run.steps.append(nav_result.step)
        run.results.append(nav_result)

        if on_progress:
            on_progress(run.id, 0, MAX_STEPS, nav_result.step, nav_result)

        state = AgentState(
            run_id=run.id,
            initial_url=url,
            goal=story,
            browser_page=page,
            browser_session=session,
            screenshot_dir=screenshot_dir,
            step_index=1,
            start_time=datetime.fromtimestamp(total_start),
            max_steps=MAX_STEPS,
        )

        step_index = 1
        while step_index < MAX_STEPS:
            if cancellation_requested():
                cancel_run()
                break

            state = state.copy_with_updates(step_index=step_index)

            obs_updates = await observe_node(state)
            state = state.copy_with_updates(**obs_updates)

            reason_updates = await reason_node(state)
            state = state.copy_with_updates(**reason_updates)

            safety_updates = await safety_node(state)
            state = state.copy_with_updates(**safety_updates)

            # Check if done
            if state.last_llm_decision and state.last_llm_decision.action == "done":
                final_result = await browser.execute_action(
                    page=page,
                    action="done",
                    target=None,
                    value=None,
                    description=state.last_llm_decision.description,
                    screenshot_dir=screenshot_dir,
                    step_index=step_index,
                )
                run.steps.append(final_result.step)
                run.results.append(final_result)

                run.goal_achieved = as_bool(state.last_llm_decision.success, default=False)

                if on_progress:
                    on_progress(run.id, step_index, step_index + 1, final_result.step, final_result)

                break

            action_updates = await action_node(state)
            state = state.copy_with_updates(**action_updates)

            if state.last_action:
                try:
                    action_type = ActionType(state.last_llm_decision.action) if state.last_llm_decision else ActionType.SCREENSHOT
                except ValueError:
                    action_type = ActionType.SCREENSHOT

                step = TestStep(
                    index=step_index,
                    action=action_type,
                    description=state.last_llm_decision.description if state.last_llm_decision else "",
                )
                result = StepResult(
                    step=step,
                    status=StepStatus.PASS if state.last_action_success else StepStatus.FAIL,
                    screenshot_path=state.last_action.screenshot_path,
                    error=state.last_action_error,
                )

                if on_progress:
                    on_progress(run.id, step_index, MAX_STEPS, step, result)

            eval_updates = await evaluate_node(state)
            state = state.copy_with_updates(**eval_updates)

            if (
                state.goal_achieved is not None
                or state.should_cancel
                or state.max_steps_reached
                or state.max_consecutive_failures_reached
            ):
                break

            step_index += 1
            await asyncio.sleep(0.3)

        if step_index >= MAX_STEPS and state.goal_achieved is None and not run.canceled:
            state = state.copy_with_updates(goal_achieved=infer_goal_status_from_results(run))

        run.goal_achieved = state.goal_achieved

        if not run.canceled:
            run.total_duration_ms = int((time.time() - total_start) * 1000)
            storage.save_run(run)

    finally:
        await session.stop()

    if run.canceled:
        completed_steps = len(run.results)
        run.summary = (
            f"Run canceled after {completed_steps} completed step"
            f"{'s' if completed_steps != 1 else ''}. "
            f"{run.cancel_reason or 'Run canceled by user.'}"
        )
    else:
        run.summary = reporter.generate_summary(run)

    storage.save_run(run)
    return run
