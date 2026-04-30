from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
import time


class StepStatus(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    CANCELED = "canceled"


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"
    ASSERT_ELEMENT = "assert_element"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    SCROLL = "scroll"
    SELECT = "select"
    HOVER = "hover"


@dataclass
class TestStep:
    index: int
    action: ActionType
    description: str
    target: Optional[str] = None      # CSS selector or URL
    value: Optional[str] = None       # text to type, option to select, etc.
    assertion: Optional[str] = None   # expected text/url to assert


@dataclass
class StepResult:
    step: TestStep
    status: StepStatus
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class TestRun:
    id: str
    url: str
    story: str
    created_at: float = field(default_factory=time.time)
    steps: List[TestStep] = field(default_factory=list)
    results: List[StepResult] = field(default_factory=list)
    summary: Optional[str] = None
    total_duration_ms: int = 0
    goal_achieved: Optional[bool] = None  # Set by agentic loop's final verdict
    canceled: bool = False
    cancel_reason: Optional[str] = None

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == StepStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == StepStatus.FAIL)

    @property
    def overall_status(self) -> StepStatus:
        if self.canceled:
            return StepStatus.CANCELED
        if not self.results:
            return StepStatus.PENDING
        # If the agentic loop made a final verdict, use it
        if self.goal_achieved is not None:
            return StepStatus.PASS if self.goal_achieved else StepStatus.FAIL
        # Fallback: check individual step results
        if any(r.status == StepStatus.FAIL for r in self.results):
            return StepStatus.FAIL
        return StepStatus.PASS
