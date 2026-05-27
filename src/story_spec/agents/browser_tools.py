"""
LangChain tool wrappers for browser actions.

Each action (click, type, select, scroll, etc.) is wrapped as a traceable
LangChain tool that can be called by the reasoning chain and tracked in LangSmith.

These tools delegate to the existing browser.execute_action() but add
proper typing, validation, and tracing.
"""

from typing import Optional, Annotated
from pathlib import Path
from playwright.async_api import Page

from langchain_core.tools import tool
from pydantic import Field

from story_spec.agents import browser
from story_spec.core.models import StepResult

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


@traceable
@tool
async def click_tool(
    page: Page,
    selector: Annotated[str, Field(description="CSS selector of element to click")],
    description: Annotated[str, Field(description="Action description")] = "Click element",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Click on an element identified by CSS selector."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="click",
            target=selector,
            value=None,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def type_tool(
    page: Page,
    selector: Annotated[str, Field(description="CSS selector of input field")],
    text: Annotated[str, Field(description="Text to type")],
    description: Annotated[str, Field(description="Action description")] = "Type text",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Type text into an input field (field will be cleared first)."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="type",
            target=selector,
            value=text,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def select_tool(
    page: Page,
    selector: Annotated[str, Field(description="CSS selector of select element")],
    option: Annotated[str, Field(description="Option text or value to select")],
    description: Annotated[str, Field(description="Action description")] = "Select option",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Select an option from a dropdown."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="select",
            target=selector,
            value=option,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def scroll_tool(
    page: Page,
    direction: Annotated[str, Field(description="Direction: 'up', 'down', or pixel amount")],
    description: Annotated[str, Field(description="Action description")] = "Scroll page",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Scroll the page."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="scroll",
            target=None,
            value=direction,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def wait_tool(
    page: Page,
    milliseconds: Annotated[int, Field(description="Milliseconds to wait")],
    description: Annotated[str, Field(description="Action description")] = "Wait",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Wait/pause execution."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="wait",
            target=None,
            value=str(milliseconds),
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def screenshot_tool(
    page: Page,
    description: Annotated[str, Field(description="Action description")] = "Take screenshot",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Take a screenshot of the current page."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="screenshot",
            target=None,
            value=None,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def navigate_tool(
    page: Page,
    url: Annotated[str, Field(description="Full URL to navigate to")],
    description: Annotated[str, Field(description="Action description")] = "Navigate",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Navigate to a URL."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="navigate",
            target=url,
            value=None,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


@traceable
@tool
async def hover_tool(
    page: Page,
    selector: Annotated[str, Field(description="CSS selector of element to hover")],
    description: Annotated[str, Field(description="Action description")] = "Hover element",
    screenshot_dir: Path = Path.cwd(),
    step_index: int = 0,
) -> dict:
    """Hover over an element."""
    try:
        result: StepResult = await browser.execute_action(
            page=page,
            action="hover",
            target=selector,
            value=None,
            description=description,
            screenshot_dir=screenshot_dir,
            step_index=step_index,
        )
        return {
            "success": result.status.value == "pass",
            "error": result.error,
            "screenshot": result.screenshot_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "screenshot": None,
        }


# Dictionary of all available tools
BROWSER_TOOLS = {
    "click": click_tool,
    "type": type_tool,
    "select": select_tool,
    "scroll": scroll_tool,
    "wait": wait_tool,
    "screenshot": screenshot_tool,
    "navigate": navigate_tool,
    "hover": hover_tool,
}
