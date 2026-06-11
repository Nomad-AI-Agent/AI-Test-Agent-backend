"""State models for the LangGraph-based autonomous browser testing agent."""

from typing import Optional, Any, Dict, List
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel, Field


class ActionSnapshot(BaseModel):
    """Snapshot of an executed action."""
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    description: str = ""
    success: bool = False
    error: Optional[str] = None
    screenshot_path: Optional[str] = None


class LLMDecision(BaseModel):
    """Decision made by the LLM."""
    thought: str
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    description: str = ""
    success: Optional[bool] = None


class AgentState(BaseModel):
    """State for the LangGraph agent."""
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
    max_steps: int
    max_consecutive_failures: int = 3
    max_search_scrolls: int = 6
    screenshot_dir: Optional[Path] = None

    # Observability
    start_time: Optional[datetime] = None
    total_duration_ms: int = 0

    class Config:
        arbitrary_types_allowed = True

    def copy_with_updates(self, **kwargs) -> "AgentState":
        """Create a copy with updated fields."""
        return self.model_copy(update=kwargs)

    @property
    def reached_max_steps(self) -> bool:
        """Check if max steps reached."""
        return self.step_index >= self.max_steps

    @property
    def max_consecutive_failures_reached(self) -> bool:
        """Check if max consecutive failures reached."""
        return self.failure_count >= self.max_consecutive_failures

    @property
    def should_terminate(self) -> bool:
        """Check if agent should terminate."""
        return (
            self.should_cancel
            or self.max_steps_reached
            or self.max_consecutive_failures_reached
            or self.goal_achieved is not None
        )
