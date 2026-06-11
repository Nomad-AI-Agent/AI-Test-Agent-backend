"""LangGraph node implementations for the autonomous browser testing agent."""

import time
from typing import Optional, Any, Dict, Callable
from pathlib import Path

from story_spec.core.state import AgentState, ActionSnapshot, LLMDecision
from story_spec.core.models import TestRun, StepResult, TestStep, StepStatus, ActionType
from story_spec.core.goal_eval import coerce_duplicate_high_impact_decision, coerce_exhausted_search_decision
from story_spec.core.runner_utils import as_bool
from story_spec.agents import parser, browser, analyzer, reporter
from story_spec.core import storage

# Import tracing decorator
try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(fn):
            return fn
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


@traceable(name="observe", run_type="tool")
async def observe_node(state: AgentState) -> Dict[str, Any]:
    """Extract and format current page state."""
    page = state.browser_page
    if not page:
        return {"last_page_context": {}, "last_page_context_str": "Error: No browser page available"}

    try:
        context = await analyzer.get_page_context(page)
        context_str = analyzer.format_page_context(context)
        return {
            "last_page_context": context,
            "last_page_context_str": context_str,
            "current_url": page.url,
            "current_page_title": context.get("title", ""),
        }
    except Exception as e:
        error_msg = f"URL: {page.url if page else 'unknown'}\nError extracting page context: {str(e)}"
        return {
            "last_page_context": {},
            "last_page_context_str": error_msg,
            "llm_error": str(e),
        }


@traceable(name="reason", run_type="llm")
async def reason_node(state: AgentState) -> Dict[str, Any]:
    """Call LLM to decide next action."""
    last_error = None
    if state.action_history and not state.action_history[-1].get("success"):
        last_error = state.action_history[-1].get("error")

    try:
        decision = parser.decide_next_action(
            goal=state.goal,
            page_context_str=state.last_page_context_str,
            history=state.action_history,
            error_context=last_error,
        )

        llm_decision = LLMDecision(
            thought=decision.get("thought", ""),
            action=decision.get("action", "screenshot"),
            target=decision.get("target"),
            value=decision.get("value"),
            description=decision.get("description", ""),
            success=decision.get("success"),
        )

        return {
            "last_llm_thought": llm_decision.thought,
            "last_llm_decision": llm_decision,
            "llm_error": None,
        }
    except Exception as e:
        error_text = str(e).strip() or e.__class__.__name__
        fallback_decision = LLMDecision(
            thought=f"LLM error: {error_text}",
            action="screenshot",
            description=f"Screenshot (LLM call failed: {error_text[:120]})",
        )
        return {
            "last_llm_decision": fallback_decision,
            "llm_error": str(e),
        }


@traceable(name="safety", run_type="tool")
async def safety_node(state: AgentState) -> Dict[str, Any]:
    """Apply guardrails to LLM decisions."""
    if not state.last_llm_decision:
        return {}

    decision_dict = state.last_llm_decision.model_dump()

    # Pass initial_url so coercion can check if URL actually changed
    coerced = coerce_duplicate_high_impact_decision(
        decision_dict,
        state.action_history,
        state.last_page_context,
        initial_url=state.initial_url,
    )
    coerced = coerce_exhausted_search_decision(coerced, state.action_history)

    if coerced != decision_dict:
        coerced_decision = LLMDecision(
            thought=coerced.get("thought", state.last_llm_decision.thought),
            action=coerced.get("action", state.last_llm_decision.action),
            target=coerced.get("target"),
            value=coerced.get("value"),
            description=coerced.get("description", state.last_llm_decision.description),
            success=coerced.get("success"),
        )
        return {"last_llm_decision": coerced_decision}

    return {}


@traceable(name="action", run_type="tool")
async def action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the decided action on the browser."""
    page = state.browser_page
    decision = state.last_llm_decision

    if not page or not decision:
        return {
            "last_action_success": False,
            "last_action_error": "Missing page or decision",
        }

    action = decision.action
    target = decision.target
    value = decision.value
    description = decision.description or f"Step {state.step_index + 1}"

    try:
        result = await browser.execute_action(
            page=page,
            action=action,
            target=target,
            value=value,
            description=description,
            screenshot_dir=state.screenshot_dir or Path.cwd(),
            step_index=state.step_index,
        )

        action_snapshot = ActionSnapshot(
            action=action,
            target=target,
            value=value,
            description=description,
            success=result.status == StepStatus.PASS,
            error=result.error,
            screenshot_path=result.screenshot_path,
        )

        history_item = {
            "action": action,
            "target": target,
            "value": value,
            "description": description,
            "success": result.status == StepStatus.PASS,
            "error": result.error,
        }

        return {
            "last_action": action_snapshot,
            "last_action_success": result.status == StepStatus.PASS,
            "last_action_error": result.error,
            "action_history": state.action_history + [history_item],
            "step_index": state.step_index + 1,
        }

    except Exception as e:
        action_snapshot = ActionSnapshot(
            action=action,
            target=target,
            value=value,
            description=description,
            success=False,
            error=str(e),
        )
        return {
            "last_action": action_snapshot,
            "last_action_success": False,
            "last_action_error": str(e),
        }


@traceable(name="evaluate", run_type="tool")
async def evaluate_node(state: AgentState) -> Dict[str, Any]:
    """Evaluate progress and check termination conditions."""
    updates = {}

    updates["failure_count"] = 0 if state.last_action_success else state.failure_count + 1

    if state.reached_max_steps:
        updates["max_steps_reached"] = True

    if state.max_consecutive_failures_reached:
        updates["goal_achieved"] = False
        updates["done_reason"] = "Max consecutive failures reached"

    if state.last_llm_decision and state.last_llm_decision.action == "done":
        updates["goal_achieved"] = as_bool(state.last_llm_decision.success, default=False)
        updates["done_reason"] = state.last_llm_decision.description

    return updates


async def done_node(state: AgentState, run: TestRun) -> None:
    """Finalize results and save run."""
    for i, action_item in enumerate(state.action_history):
        try:
            action_type = ActionType(action_item["action"]) if action_item["action"] != "done" else ActionType.SCREENSHOT
        except ValueError:
            action_type = ActionType.SCREENSHOT

        step = TestStep(
            index=i,
            action=action_type,
            description=action_item["description"],
            target=action_item.get("target"),
            value=action_item.get("value"),
        )

        result = StepResult(
            step=step,
            status=StepStatus.PASS if action_item.get("success") else StepStatus.FAIL,
            screenshot_path=action_item.get("screenshot_path"),
            error=action_item.get("error"),
            duration_ms=0,
        )

        run.steps.append(step)
        run.results.append(result)

    from story_spec.core.goal_eval import infer_goal_status_from_results
    run.goal_achieved = state.goal_achieved if state.goal_achieved is not None else infer_goal_status_from_results(run)

    if state.start_time:
        run.total_duration_ms = int((time.time() - state.start_time.timestamp()) * 1000)

    run.summary = reporter.generate_summary(run)
    storage.save_run(run)


def route_after_safety(state: AgentState) -> str:
    """Route after safety check: either to 'done' or 'action'."""
    if state.last_llm_decision and state.last_llm_decision.action == "done":
        return "done"
    return "action"


def route_after_action(state: AgentState) -> str:
    """Route after action execution: either back to 'observe' or to 'done'."""
    if state.should_cancel or state.max_steps_reached or state.max_consecutive_failures_reached:
        return "done"
    if state.goal_achieved is not None:
        return "done"
    return "observe"
