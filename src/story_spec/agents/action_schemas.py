"""
Strict Pydantic schemas for LLM-generated browser actions.

These schemas enforce type safety and enable structured LLM outputs
using OpenAI's function calling. The discriminated union pattern ensures
the LLM can only emit valid action types.

The LLM reasoning chain uses these schemas to produce deterministic,
validated action outputs that can be directly executed.
"""

from typing import Union, Literal, Optional
from pydantic import BaseModel, Field


class ClickAction(BaseModel):
    """Click on an element."""
    action: Literal["click"] = "click"
    target: str = Field(
        ...,
        description="CSS selector of element to click",
        example="#submit-button"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class TypeAction(BaseModel):
    """Type text into an input field."""
    action: Literal["type"] = "type"
    target: str = Field(
        ...,
        description="CSS selector of input field",
        example="input[name='email']"
    )
    value: str = Field(
        ...,
        description="Text to type (field will be cleared first)",
        example="user@example.com"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class SelectAction(BaseModel):
    """Select an option from a dropdown."""
    action: Literal["select"] = "select"
    target: str = Field(
        ...,
        description="CSS selector of select element or dropdown",
        example="select#country"
    )
    value: str = Field(
        ...,
        description="Option text or value to select",
        example="United States"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class ScrollAction(BaseModel):
    """Scroll the page."""
    action: Literal["scroll"] = "scroll"
    value: str = Field(
        ...,
        description="Direction: 'up', 'down', or pixel amount (e.g. '500')",
        example="down"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class WaitAction(BaseModel):
    """Wait/pause execution."""
    action: Literal["wait"] = "wait"
    value: str = Field(
        ...,
        description="Milliseconds to wait (e.g. '1000' for 1 second)",
        example="1500"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class ScreenshotAction(BaseModel):
    """Take a screenshot of the current page."""
    action: Literal["screenshot"] = "screenshot"
    description: str = Field(
        default="Take a screenshot to see page state",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class NavigateAction(BaseModel):
    """Navigate to a URL."""
    action: Literal["navigate"] = "navigate"
    target: str = Field(
        ...,
        description="Full URL to navigate to",
        example="https://example.com/login"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class HoverAction(BaseModel):
    """Hover over an element."""
    action: Literal["hover"] = "hover"
    target: str = Field(
        ...,
        description="CSS selector of element to hover",
        example=".dropdown-trigger"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the action"
    )
    thought: str = Field(
        default="",
        description="Reasoning about why this action is taken"
    )


class DoneAction(BaseModel):
    """Goal achieved or failed — stop execution."""
    action: Literal["done"] = "done"
    success: bool = Field(
        ...,
        description="True if goal was achieved, False if it failed"
    )
    description: str = Field(
        ...,
        description="Final assessment: what was accomplished or why it failed",
        example="Goal achieved: user account created successfully"
    )
    thought: str = Field(
        default="",
        description="Reasoning about goal achievement or failure"
    )


# Discriminated union for all valid actions
Action = Union[
    ClickAction,
    TypeAction,
    SelectAction,
    ScrollAction,
    WaitAction,
    ScreenshotAction,
    NavigateAction,
    HoverAction,
    DoneAction,
]


def action_to_dict(action: Action) -> dict:
    """Convert Pydantic action model to dictionary format."""
    data = action.model_dump(exclude_none=True)
    return data


def dict_to_action(data: dict) -> Optional[Action]:
    """Convert dictionary to Pydantic action model."""
    if not isinstance(data, dict):
        return None

    action_type = data.get("action")

    try:
        if action_type == "click":
            return ClickAction(**data)
        elif action_type == "type":
            return TypeAction(**data)
        elif action_type == "select":
            return SelectAction(**data)
        elif action_type == "scroll":
            return ScrollAction(**data)
        elif action_type == "wait":
            return WaitAction(**data)
        elif action_type == "screenshot":
            return ScreenshotAction(**data)
        elif action_type == "navigate":
            return NavigateAction(**data)
        elif action_type == "hover":
            return HoverAction(**data)
        elif action_type == "done":
            return DoneAction(**data)
        else:
            return None
    except Exception:
        return None
