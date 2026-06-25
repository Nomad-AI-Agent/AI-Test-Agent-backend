from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    CANCELED = "canceled"
    PAUSED = "paused"


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
class Project:
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TargetConfig:
    url: str
    role: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.role or 'default'}] {self.url}"


@dataclass
class TestStep:
    index: int
    action: ActionType
    description: str
    target: Optional[str] = None      # CSS selector or URL
    value: Optional[str] = None       # text to type, option to select, etc.
    assertion: Optional[str] = None   # expected text/url to assert
    target_index: int = 0             # which target this step belongs to


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
    targets: List[TargetConfig]
    story: str
    current_target_index: int = 0
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps: List[TestStep] = field(default_factory=list)
    results: List[StepResult] = field(default_factory=list)
    summary: Optional[str] = None
    total_duration_ms: int = 0
    goal_achieved: Optional[bool] = None  # Set by agentic loop's final verdict
    canceled: bool = False
    cancel_reason: Optional[str] = None
    paused: bool = False
    pause_checkpoint: Optional[Dict] = None  # Stores pause state for resume
    video_path: Optional[str] = None  # URL or local path to recorded video

    @property
    def current_target(self) -> TargetConfig:
        return self.targets[self.current_target_index]

    @property
    def url(self) -> str:
        """Backward-compat: returns first target's URL."""
        return self.targets[0].url if self.targets else ""

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == StepStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == StepStatus.FAIL)

    @property
    def overall_status(self) -> StepStatus:
        if self.paused:
            return StepStatus.PAUSED
        if self.canceled:
            return StepStatus.CANCELED
        if not self.results:
            return StepStatus.PENDING
        # No final verdict yet — run is still in progress (including after resume)
        if self.goal_achieved is None:
            return StepStatus.PENDING
        return StepStatus.PASS if self.goal_achieved else StepStatus.FAIL
