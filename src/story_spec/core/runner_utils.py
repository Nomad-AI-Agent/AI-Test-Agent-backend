"""Utility functions for the LangGraph runner."""

import re
from typing import Optional, Dict, Any, List, Set

# Constants for goal evaluation
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
    "success", "successfully", "created", "saved", "confirmed",
}

MAX_SEARCH_SCROLLS = 6


def as_bool(value: Any, default: bool = False) -> bool:
    """Convert a value to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return default


def contains_any(text: str, keywords: Set[str]) -> bool:
    """Check if text contains any of the keywords (case-insensitive)."""
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def decision_text(action: str, target: Optional[str], value: Optional[str], description: str) -> str:
    """Format a decision as text for analysis."""
    return " ".join(part for part in [action, target or "", value or "", description or ""] if part)


def is_high_impact_action(action: str, target: Optional[str], value: Optional[str], description: str) -> bool:
    """Check if an action is high-impact (create, save, submit, etc.)."""
    if action not in {"click", "select"}:
        return False
    return contains_any(decision_text(action, target, value, description), HIGH_IMPACT_KEYWORDS)


def same_decision(decision: Dict[str, Any], history_item: Dict[str, Any]) -> bool:
    """Check if two decisions are the same."""
    return (
        decision.get("action") == history_item.get("action")
        and (decision.get("target") or None) == (history_item.get("target") or None)
        and (decision.get("value") or None) == (history_item.get("value") or None)
    )


def was_successfully_done_before(decision: Dict[str, Any], history: List[Dict[str, Any]]) -> bool:
    """Check if this decision was already successfully executed."""
    for item in reversed(history):
        if item.get("success") and same_decision(decision, item):
            return True
    return False


def selector_still_visible(context: Dict[str, Any], selector: Optional[str]) -> bool:
    """Check if a CSS selector is still visible in the page context."""
    if not selector:
        return False
    for key in ("inputs", "checkables", "buttons", "links"):
        for item in context.get(key, []):
            if item.get("selector") == selector:
                return True
    return False


def page_has_error_signal(context: Dict[str, Any]) -> bool:
    """Check if page shows error signals."""
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(contains_any(text, ERROR_HINTS) for text in haystacks)


def page_has_success_signal(context: Dict[str, Any]) -> bool:
    """Check if page shows success signals."""
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(contains_any(text, SUCCESS_HINTS) for text in haystacks)


def recent_consecutive_action_count(history: List[Dict[str, Any]], action: str) -> int:
    """Count recent consecutive successful actions of a given type."""
    count = 0
    for item in reversed(history):
        if item.get("action") != action or not item.get("success"):
            break
        count += 1
    return count


def extract_entity_name(text: str) -> Optional[str]:
    """Extract entity name from text (e.g., from 'for the Acme Corp' -> 'Acme Corp')."""
    if not text:
        return None
    quoted = re.search(r"'([^']+)'|\"([^\"]+)\"", text)
    if quoted:
        return quoted.group(1) or quoted.group(2)
    match = re.search(r"for the ([^.]+?)(?: organization| link| page| details)?$", text.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
