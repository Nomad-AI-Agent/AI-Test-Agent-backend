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
import re
import time
import json
from typing import Optional, Callable, List, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

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
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

from story_spec.core.models import TestRun, StepResult, TestStep, StepStatus
from story_spec.core import storage, config
from story_spec.agents import parser, browser, analyzer, reporter
from story_spec.core.models import ActionType

ProgressCallback = Callable[[str, int, int, TestStep, StepResult], None]
CancelCallback = Callable[[], bool]

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
# Tightened: removed "dashboard", "overview", "welcome", "done", "completed"
# to prevent false-positive goal detection on common page words
SUCCESS_HINTS = {
    "success", "successfully", "created", "saved", "confirmed",
}
MAX_SEARCH_SCROLLS = 6


# ============================================================================
# STATE DEFINITION
# ============================================================================

class ActionSnapshot(BaseModel):
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    description: str = ""
    success: bool = False
    error: Optional[str] = None
    screenshot_path: Optional[str] = None


class LLMDecision(BaseModel):
    thought: str
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    description: str = ""
    success: Optional[bool] = None


class AgentState(BaseModel):
    # Run metadata
    run_id: str
    initial_url: str
    goal: str

    # Browser state
    current_url: str = ""
    current_page_title: str = ""
    browser_page: Optional[Any] = Field(default=None, exclude=True)
    browser_session: Optional[Any] = Field(default=None, exclude=True)

    # Observation
    last_page_context: Dict[str, Any] = Field(default_factory=dict)
    last_page_context_str: str = ""

    # Reasoning
    last_llm_thought: str = ""
    last_llm_decision: Optional[LLMDecision] = None
    llm_error: Optional[str] = None

    # Action execution
    last_action: Optional[ActionSnapshot] = None
    last_action_success: bool = False
    last_action_error: Optional[str] = None

    # History & tracking
    action_history: List[Dict[str, Any]] = Field(default_factory=list)
    step_index: int = 0
    failure_count: int = 0
    search_scroll_count: int = 0

    # Goal status
    goal_achieved: Optional[bool] = None
    done_reason: Optional[str] = None

    # Termination & cancellation
    should_cancel: bool = False
    cancel_reason: Optional[str] = None
    max_steps_reached: bool = False

    # Configuration
    max_steps: int = MAX_STEPS
    max_consecutive_failures: int = 3
    max_search_scrolls: int = MAX_SEARCH_SCROLLS
    screenshot_dir: Optional[Path] = None

    # Observability
    start_time: Optional[datetime] = None
    total_duration_ms: int = 0

    class Config:
        arbitrary_types_allowed = True

    def copy_with_updates(self, **kwargs) -> "AgentState":
        return self.model_copy(update=kwargs)

    @property
    def reached_max_steps(self) -> bool:
        return self.step_index >= self.max_steps

    @property
    def max_consecutive_failures_reached(self) -> bool:
        return self.failure_count >= self.max_consecutive_failures

    @property
    def should_terminate(self) -> bool:
        return (
            self.should_cancel
            or self.max_steps_reached
            or self.max_consecutive_failures_reached
            or self.goal_achieved is not None
        )


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

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


def _contains_any(text: str, keywords: set) -> bool:
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


def _recent_consecutive_action_count(history: List[Dict[str, Any]], action: str) -> int:
    count = 0
    for item in reversed(history):
        if item.get("action") != action or not item.get("success"):
            break
        count += 1
    return count


def _extract_entity_name(text: str) -> Optional[str]:
    if not text:
        return None
    quoted = re.search(r"'([^']+)'|\"([^\"]+)\"", text)
    if quoted:
        return quoted.group(1) or quoted.group(2)
    match = re.search(r"for the ([^.]+?)(?: organization| link| page| details)?$", text.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _recent_missing_entity_failure(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    recent_scrolls = _recent_consecutive_action_count(history, "scroll")
    if recent_scrolls < 3:
        return None
    for item in reversed(history):
        if item.get("action") == "scroll" and item.get("success"):
            continue
        if (
            item.get("action") in {"click", "select"}
            and not item.get("success")
            and "element not found" in (item.get("error") or "").lower()
        ):
            return item
        break
    return None


def _coerce_exhausted_search_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    recent_scrolls = _recent_consecutive_action_count(history, "scroll")

    missing_item_failure = _recent_missing_entity_failure(history)
    if missing_item_failure and decision.get("action") in {"scroll", "wait", "screenshot"}:
        entity_name = _extract_entity_name(missing_item_failure.get("description", ""))
        target_text = entity_name or "the requested item"
        return {
            "thought": f"After repeated search attempts, {target_text} still is not present in the UI.",
            "action": "done",
            "description": f"Goal failed: {target_text} was not found after repeated search attempts.",
            "success": False,
        }

    if decision.get("action") == "scroll" and recent_scrolls >= MAX_SEARCH_SCROLLS:
        return {
            "thought": "Repeated scrolling has not revealed the requested item, so continuing is unlikely to help.",
            "action": "done",
            "description": "Goal failed: the requested item was not found after repeated scrolling/search attempts.",
            "success": False,
        }

    return decision


def _coerce_duplicate_high_impact_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
    context: Dict[str, Any],
    initial_url: str = "",
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

    current_url = context.get("url", "")
    url_changed = initial_url and current_url and current_url != initial_url

    # Only declare done:true if URL changed AND page has a success signal.
    # Previously this fired on selector-disappear alone, causing false positives.
    if url_changed and _page_has_success_signal(context):
        return {
            "thought": "The same irreversible action already succeeded once and the page now indicates the workflow completed.",
            "action": "done",
            "description": f"Goal achieved after {description or action}",
            "success": True,
        }

    # Selector disappeared but no clear success signal — take a screenshot and
    # let the LLM decide rather than assuming success.
    if not _selector_still_visible(context, target):
        return {
            "thought": "The element is no longer visible after the previous action. Capturing page state for assessment.",
            "action": "screenshot",
            "description": "Capture page state to assess whether goal was achieved",
        }

    return {
        "thought": "The same irreversible action already succeeded once. Waiting for the UI to settle.",
        "action": "wait",
        "value": "1200",
        "description": "Wait for the page to settle after a successful submission",
    }


def _infer_goal_status_from_results(run: TestRun) -> Optional[bool]:
    if any(result.status == StepStatus.FAIL for result in run.results):
        return False
    if run.results and all(result.status == StepStatus.PASS for result in run.results):
        return None
    return None


# ============================================================================
# GRAPH NODES
# ============================================================================

@traceable(name="observe", run_type="tool")
async def observe_node(state: AgentState) -> Dict[str, Any]:
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
    if not state.last_llm_decision:
        return {}

    decision_dict = state.last_llm_decision.model_dump()

    # Pass initial_url so coercion can check if URL actually changed
    coerced = _coerce_duplicate_high_impact_decision(
        decision_dict,
        state.action_history,
        state.last_page_context,
        initial_url=state.initial_url,
    )
    coerced = _coerce_exhausted_search_decision(coerced, state.action_history)

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
    updates = {}

    updates["failure_count"] = 0 if state.last_action_success else state.failure_count + 1

    if state.reached_max_steps:
        updates["max_steps_reached"] = True

    if state.max_consecutive_failures_reached:
        updates["goal_achieved"] = False
        updates["done_reason"] = "Max consecutive failures reached"

    if state.last_llm_decision and state.last_llm_decision.action == "done":
        updates["goal_achieved"] = _as_bool(state.last_llm_decision.success, default=False)
        updates["done_reason"] = state.last_llm_decision.description

    return updates


async def done_node(state: AgentState, run: TestRun) -> None:
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

    run.goal_achieved = state.goal_achieved if state.goal_achieved is not None else _infer_goal_status_from_results(run)

    if state.start_time:
        run.total_duration_ms = int((time.time() - state.start_time.timestamp()) * 1000)

    run.summary = reporter.generate_summary(run)
    storage.save_run(run)


# ============================================================================
# CONDITIONAL EDGES / ROUTING
# ============================================================================

def route_after_safety(state: AgentState) -> str:
    if state.last_llm_decision and state.last_llm_decision.action == "done":
        return "done"
    return "action"


def route_after_action(state: AgentState) -> str:
    if state.should_cancel or state.max_steps_reached or state.max_consecutive_failures_reached:
        return "done"
    if state.goal_achieved is not None:
        return "done"
    return "observe"


# ============================================================================
# BUILD LANGGRAPH
# ============================================================================

def build_graph():
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


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

@traceable(name="agent-execute", run_type="chain")
async def execute(
    url: str,
    story: str,
    headless: bool = True,
    on_progress: Optional[ProgressCallback] = None,
    run_id: Optional[str] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> TestRun:
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

                run.goal_achieved = _as_bool(state.last_llm_decision.success, default=False)

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
            state = state.copy_with_updates(goal_achieved=_infer_goal_status_from_results(run))

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