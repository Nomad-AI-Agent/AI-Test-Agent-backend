"""Goal evaluation logic for the LangGraph runner."""

from typing import Optional, Dict, List, Any

from story_spec.core.models import TestRun, StepStatus
from .runner_utils import (
    recent_consecutive_action_count,
    extract_entity_name,
    contains_any,
    selector_still_visible,
    page_has_error_signal,
    page_has_success_signal,
    as_bool,
    MAX_SEARCH_SCROLLS,
)


def recent_missing_entity_failure(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Check if we recently tried to click/select something that wasn't found.
    
    Returns the failing item if we have 3+ recent scrolls without success.
    """
    recent_scrolls = recent_consecutive_action_count(history, "scroll")
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


def coerce_exhausted_search_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Apply guardrails for exhausted search attempts.
    
    If we've scrolled repeatedly looking for something and it's still not there,
    convert scroll/wait/screenshot to done:false.
    """
    missing_item_failure = recent_missing_entity_failure(history)
    if missing_item_failure and decision.get("action") in {"scroll", "wait", "screenshot"}:
        entity_name = extract_entity_name(missing_item_failure.get("description", ""))
        target_text = entity_name or "the requested item"
        return {
            "thought": f"After repeated search attempts, {target_text} still is not present in the UI.",
            "action": "done",
            "description": f"Goal failed: {target_text} was not found after repeated search attempts.",
            "success": False,
        }

    recent_scrolls = recent_consecutive_action_count(history, "scroll")
    if decision.get("action") == "scroll" and recent_scrolls >= MAX_SEARCH_SCROLLS:
        return {
            "thought": "Repeated scrolling has not revealed the requested item, so continuing is unlikely to help.",
            "action": "done",
            "description": "Goal failed: the requested item was not found after repeated scrolling/search attempts.",
            "success": False,
        }

    return decision


def coerce_duplicate_high_impact_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
    context: Dict[str, Any],
    initial_url: str = "",
) -> Dict[str, Any]:
    """
    Apply guardrails for repeated high-impact actions.
    
    If we already successfully clicked "Create/Submit/Save" once, prevent duplicate
    submissions that could cause errors or duplicate data.
    """
    from .runner_utils import is_high_impact_action, same_decision, decision_text
    
    action = decision.get("action", "screenshot")
    target = decision.get("target")
    value = decision.get("value")
    description = decision.get("description", "")

    if not is_high_impact_action(action, target, value, description):
        return decision
    
    # Check if this action was already successfully completed
    from .runner_utils import was_successfully_done_before
    if not was_successfully_done_before(decision, history):
        return decision

    if page_has_error_signal(context):
        return {
            "thought": "The same high-impact action already succeeded once and the page now shows validation or error feedback.",
            "action": "screenshot",
            "description": "Capture page state after validation or error feedback",
        }

    current_url = context.get("url", "")
    url_changed = initial_url and current_url and current_url != initial_url

    # Only declare done:true if URL changed AND page has a success signal.
    if url_changed and page_has_success_signal(context):
        return {
            "thought": "The same irreversible action already succeeded once and the page now indicates the workflow completed.",
            "action": "done",
            "description": f"Goal achieved after {description or action}",
            "success": True,
        }

    # Selector disappeared but no clear success signal — take a screenshot
    if not selector_still_visible(context, target):
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


def infer_goal_status_from_results(run: TestRun) -> Optional[bool]:
    """
    Infer the final run verdict when the LLM never returns an explicit `done`.
    
    If any step failed, the run should fail. If every executed step passed,
    return None so the fallback logic treats it as passed.
    """
    if any(result.status == StepStatus.FAIL for result in run.results):
        return False
    if run.results and all(result.status == StepStatus.PASS for result in run.results):
        return None
    return None
