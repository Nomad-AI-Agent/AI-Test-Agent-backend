"""Event management for server-sent events (SSE) streaming."""

from typing import Optional, Dict, List, Any


# Global state for managing run events
_run_events: Dict[str, List[Dict[str, Any]]] = {}   # run_id -> list[dict]
_run_done: Dict[str, bool] = {}                       # run_id -> bool
_run_cancel: Dict[str, bool] = {}                     # run_id -> bool


def push_event(run_id: str, data: dict) -> None:
    """Push an event to the event stream for a specific run."""
    if run_id not in _run_events:
        _run_events[run_id] = []
    _run_events[run_id].append(data)


def get_events(run_id: str) -> List[Dict[str, Any]]:
    """Get all events for a run."""
    return _run_events.get(run_id, [])


def mark_done(run_id: str) -> None:
    """Mark a run as done."""
    _run_done[run_id] = True


def is_done(run_id: str) -> bool:
    """Check if a run is done."""
    return _run_done.get(run_id, False)


def request_cancel(run_id: str) -> None:
    """Request cancellation of a run."""
    _run_cancel[run_id] = True


def should_cancel(run_id: str) -> bool:
    """Check if cancellation was requested for a run."""
    return _run_cancel.get(run_id, False)


def cleanup(run_id: str) -> None:
    """Clean up event state for a run."""
    _run_cancel.pop(run_id, None)


def initialize_run(run_id: str) -> None:
    """Initialize event state for a new run."""
    _run_events[run_id] = []
    _run_done[run_id] = False
    _run_cancel[run_id] = False
