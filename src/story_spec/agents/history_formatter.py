"""Formatting utilities for action history."""

from typing import List, Dict, Any


def format_action_history(history: List[Dict[str, Any]]) -> str:
    """Format action history for inclusion in LLM prompt."""
    if not history:
        return "No actions taken yet. This is the starting page after initial navigation."

    lines = []
    for i, h in enumerate(history, 1):
        status = "SUCCESS" if h.get("success") else "FAILED"
        line = f"  Step {i}: [{status}] {h['action'].upper()} - {h['description']}"
        if h.get("error"):
            line += f"\n    Error: {h['error']}"
        lines.append(line)

    return "ACTIONS TAKEN SO FAR:\n" + "\n".join(lines)
