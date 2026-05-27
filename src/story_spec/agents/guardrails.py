"""
Guardrails and safety coercion logic for the agent.

These are the three core guardrails that prevent infinite loops,
duplicate high-impact actions, and exhaustion from repeated search attempts.

These guardrails are preserved exactly as they were in the original runner.py
and are integrated into the safety node of the graph.
"""

from typing import Dict, List, Any, Optional
import re


# Constants from original runner.py
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

MAX_SEARCH_SCROLLS = 6


def _contains_any(text: str, keywords: set) -> bool:
    """Check if text contains any of the keywords."""
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _decision_text(
    action: str,
    target: Optional[str],
    value: Optional[str],
    description: str
) -> str:
    """Build decision text for keyword matching."""
    return " ".join(part for part in [action, target or "", value or "", description or ""] if part)


def _is_high_impact_action(
    action: str,
    target: Optional[str],
    value: Optional[str],
    description: str
) -> bool:
    """Check if action is high-impact (irreversible)."""
    if action not in {"click", "select"}:
        return False
    return _contains_any(
        _decision_text(action, target, value, description),
        HIGH_IMPACT_KEYWORDS
    )


def _same_decision(
    decision: Dict[str, Any],
    history_item: Dict[str, Any]
) -> bool:
    """Check if two decisions are the same."""
    return (
        decision.get("action") == history_item.get("action")
        and (decision.get("target") or None) == (history_item.get("target") or None)
        and (decision.get("value") or None) == (history_item.get("value") or None)
    )


def _was_successfully_done_before(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]]
) -> bool:
    """Check if same decision succeeded before."""
    for item in reversed(history):
        if item.get("success") and _same_decision(decision, item):
            return True
    return False


def _selector_still_visible(
    context: Dict[str, Any],
    selector: Optional[str]
) -> bool:
    """Check if a selector is still visible on the page."""
    if not selector:
        return False
    for key in ("inputs", "checkables", "buttons", "links"):
        for item in context.get(key, []):
            if item.get("selector") == selector:
                return True
    return False


def _page_has_error_signal(context: Dict[str, Any]) -> bool:
    """Check if page shows error signals."""
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(_contains_any(text, ERROR_HINTS) for text in haystacks)


def _page_has_success_signal(context: Dict[str, Any]) -> bool:
    """Check if page shows success signals."""
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(_contains_any(text, SUCCESS_HINTS) for text in haystacks)


def _recent_consecutive_action_count(
    history: List[Dict[str, Any]],
    action: str
) -> int:
    """Count recent consecutive actions of a specific type."""
    count = 0
    for item in reversed(history):
        if item.get("action") != action or not item.get("success"):
            break
        count += 1
    return count


def _extract_entity_name(text: str) -> Optional[str]:
    """Extract entity name from description text."""
    if not text:
        return None
    quoted = re.search(r"'([^']+)'|\"([^\"]+)\"", text)
    if quoted:
        return quoted.group(1) or quoted.group(2)
    match = re.search(
        r"for the ([^.]+?)(?: organization| link| page| details)?$",
        text.strip(),
        re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    return None


def _recent_missing_entity_failure(
    history: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    GUARDRAIL #3: Detect when entity is missing after repeated searches.

    Returns the original failed search action if:
    1. Recent scrolls >= 3
    2. Last non-scroll action was a failed click/select with "element not found"
    """
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


def coerce_duplicate_high_impact_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    GUARDRAIL #1: Prevent duplicate high-impact actions.

    High-impact actions (create, save, submit, etc.) should not be
    executed twice. If we already succeeded, either:
    - Take a screenshot to see result
    - Wait for UI to settle
    - Mark as done if goal appears completed
    """
    action = decision.get("action", "screenshot")
    target = decision.get("target")
    value = decision.get("value")
    description = decision.get("description", "")

    if not _is_high_impact_action(action, target, value, description):
        return decision

    if not _was_successfully_done_before(decision, history):
        return decision

    # Same high-impact action succeeded before
    if _page_has_error_signal(context):
        # Page shows error — take screenshot to see error details
        return {
            "thought": "The same high-impact action already succeeded once and the page now shows validation or error feedback.",
            "action": "screenshot",
            "description": "Capture page state after validation or error feedback",
        }

    if _page_has_success_signal(context) or not _selector_still_visible(context, target):
        # Page shows success or element is gone — goal likely achieved
        return {
            "thought": "The same irreversible action already succeeded once and the page now indicates the workflow likely completed.",
            "action": "done",
            "description": f"Goal achieved after {description or action}",
            "success": True,
        }

    # Wait for UI to settle
    return {
        "thought": "The same irreversible action already succeeded once. Wait for the UI to settle before taking another step.",
        "action": "wait",
        "value": "1200",
        "description": "Wait for the page to settle after a successful submission",
    }


def coerce_exhausted_search_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    GUARDRAIL #2: Stop searching when entity can't be found.

    If we've scrolled many times looking for something that's not there,
    stop and mark the goal as failed.
    """
    recent_scrolls = _recent_consecutive_action_count(history, "scroll")

    missing_item_failure = _recent_missing_entity_failure(history)
    if missing_item_failure and decision.get("action") in {"scroll", "wait", "screenshot"}:
        # We found an earlier failed search for a specific entity
        entity_name = _extract_entity_name(missing_item_failure.get("description", ""))
        target_text = entity_name or "the requested item"
        return {
            "thought": f"After repeated search attempts, {target_text} still is not present in the UI.",
            "action": "done",
            "description": f"Goal failed: {target_text} was not found after repeated search attempts.",
            "success": False,
        }

    if decision.get("action") == "scroll" and recent_scrolls >= MAX_SEARCH_SCROLLS:
        # Too many scrolls without finding anything
        return {
            "thought": "Repeated scrolling has not revealed the requested item, so continuing is unlikely to help.",
            "action": "done",
            "description": "Goal failed: the requested item was not found after repeated scrolling/search attempts.",
            "success": False,
        }

    return decision


def apply_guardrails(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply all guardrails in sequence.

    Order matters: check duplicate high-impact first, then exhausted search.
    """
    # GUARDRAIL #1: Prevent duplicate high-impact actions
    coerced = coerce_duplicate_high_impact_decision(decision, history, context)

    # GUARDRAIL #2: Stop exhausted searches
    coerced = coerce_exhausted_search_decision(coerced, history)

    return coerced
