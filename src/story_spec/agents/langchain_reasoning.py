"""
LangChain-based reasoning chain for autonomous browser testing.

Replaces the custom parser.decide_next_action() with a real LangChain chain
that uses ChatOpenAI with structured output mode, ensuring deterministic,
validated action outputs.

This chain is fully traceable in LangSmith and supports all observability
features (token counting, timing, error tracking).
"""

import os
from typing import Optional, Dict, List, Any
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.pydantic_v1 import ValidationError

from story_spec.agents.action_schemas import Action, dict_to_action
from story_spec.core import config

# Import tracing decorator (will be set up in observability module)
try:
    from langsmith import traceable
except ImportError:
    # Fallback: define a no-op decorator if langsmith not available yet
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


SYSTEM_PROMPT = """You are an AI browser automation agent. You can see the current state of a web page and must decide what action to take next to achieve the user's goal.

You work step-by-step. Each time you are called, you see the CURRENT page state and the HISTORY of actions you've already taken. You must decide the SINGLE next action to perform.

AVAILABLE ACTIONS:
- navigate   : go to a URL (provide target = full URL)
- click      : click an element (provide target = CSS selector from the page context)
- type       : type text into an input (provide target = CSS selector, value = text to type)
- select     : select a dropdown option (provide target = CSS selector, value = option text)
- scroll     : scroll the page (provide value = "down", "up", or pixel amount as string)
- hover      : hover over an element (provide target = CSS selector)
- wait       : pause briefly (provide value = milliseconds as string, e.g. "1000")
- screenshot : take a screenshot of the current state
- done       : the goal has been achieved (or cannot be achieved), stop execution

RESPOND with a structured JSON action object.

When deciding the next action:
{
  "thought": "Your reasoning about what you see on the page and what to do next",
  "action": "<action name from the list above>",
  "target": "<CSS selector from the page context, OR full URL for navigate>",
  "value": "<text to type, option to select, scroll direction, or wait ms>",
  "description": "<short human-readable description of this step>"
}

When the goal is achieved or cannot be achieved:
{
  "thought": "Reasoning about why the goal is achieved or cannot be achieved",
  "action": "done",
  "success": true or false,
  "description": "Goal achieved: <what was accomplished> OR Goal failed: <why it failed>"
}

CRITICAL RULES:
1. ALWAYS use the CSS selectors provided in the page context under "-> selector:" — they are real, working selectors extracted from the live page. Do NOT invent or guess selectors.
2. If you need to type into an input field, use the EXACT selector shown next to that input in the page context.
3. Look at what's actually on the page — read the inputs, buttons, and links carefully before acting.
4. If the current page doesn't have what you need (e.g., no login form), look for a link or button to navigate there.
5. After submitting a form or clicking a button that triggers navigation, use a wait action (1500-2500ms) to let the page load.
6. When checking if a goal is achieved, look at the URL, page title, headings, and visible text for evidence.
7. If an action failed previously, try a DIFFERENT approach — do not repeat the same failing action with the same selector.
8. Be efficient — don't take unnecessary screenshots or wait steps. Go directly toward the goal.
9. If a field already contains the correct value, skip typing into it.
10. For type actions, the field will be cleared first, then your text will be typed.
11. DO NOT add extra assertions unless the user's story explicitly asks for verification. Focus on completing the action.
12. If you see error messages on the page after a form submission, report them in your thought and assess if the goal failed.
13. For checkboxes and radio buttons, use the provided CHECKED / NOT_CHECKED state. Only click them when the story requires changing that state.
14. For creation flows (create org, create account, submit form, save record), submission is an irreversible action. Do NOT click the final Create/Save/Submit button more than once unless the page clearly shows the first attempt failed.
15. After a successful create/save/submit action, inspect the page for success evidence before doing anything else. If the new item appears in visible text, a success message appears, or the page navigates to a details/list page for that item, respond with action="done" and success=true.
16. If the story specifies a required type, option, mode, category, or preference, explicitly choose the matching checkbox, radio button, or select option before submitting.
17. If the story depends on finding a specific named item and that item is still not visible after several search attempts or scrolls, stop and respond with action="done" and success=false instead of continuing to scroll indefinitely.
"""


def _format_action_history(history: List[Dict[str, Any]]) -> str:
    """Format action history for inclusion in prompt."""
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


class ReasoningChain:
    """Wrapper around LangChain reasoning chain."""

    def __init__(self, temperature: float = 0.1):
        """Initialize the reasoning chain."""
        self.temperature = temperature
        self.llm = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazily initialize the LLM."""
        if self._initialized:
            return

        # Use OpenRouter if available, otherwise OpenAI
        api_key = config.OPENROUTER_API_KEY or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY environment variable."
            )

        api_base = None
        if config.OPENROUTER_API_KEY:
            api_base = "https://openrouter.ai/api/v1"

        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL or "gpt-4-turbo",
            api_key=api_key,
            temperature=self.temperature,
            base_url=api_base,
            timeout=60.0,
            max_retries=2,
        ).with_structured_output(Action)

        self._initialized = True

    @traceable
    async def ainvoke(
        self,
        goal: str,
        page_context_str: str,
        history: List[Dict[str, Any]],
        error_context: Optional[str] = None,
    ) -> Action:
        """
        Call LLM asynchronously to decide next action.

        Args:
            goal: The user's goal/story
            page_context_str: Formatted current page context
            history: List of previous action results
            error_context: Error from last failed action (if any)

        Returns:
            Structured Action model
        """
        self._ensure_initialized()

        # Format prompt
        history_text = _format_action_history(history)
        error_text = f"\nLAST ACTION FAILED WITH ERROR: {error_context}" if error_context else ""

        user_prompt = f"""GOAL: {goal}

=== CURRENT PAGE STATE ===
{page_context_str}
=== END PAGE STATE ===

{history_text}
{error_text}

Special guidance:
- Complete the user's requested outcome exactly once.
- Avoid duplicate creation of the same entity.
- If a checkbox/radio required by the story is already in the correct state, leave it unchanged.

What is the next action to take?"""

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        try:
            # Invoke LLM with structured output
            result = await self.llm.ainvoke(messages)

            # Result should be an Action instance from structured output
            if isinstance(result, Action):
                return result

            # Fallback: try to parse as dict
            if isinstance(result, dict):
                action = dict_to_action(result)
                if action:
                    return action

            # Last resort: return screenshot
            from story_spec.agents.action_schemas import ScreenshotAction
            return ScreenshotAction(
                thought="Failed to parse LLM response",
                description="Taking screenshot due to parsing error"
            )

        except ValidationError as e:
            from story_spec.agents.action_schemas import ScreenshotAction
            return ScreenshotAction(
                thought=f"Structured output validation error: {str(e)[:100]}",
                description="Retrying with screenshot"
            )
        except Exception as e:
            from story_spec.agents.action_schemas import ScreenshotAction
            return ScreenshotAction(
                thought=f"LLM call failed: {str(e)[:100]}",
                description="Fallback: taking screenshot"
            )

    def invoke(
        self,
        goal: str,
        page_context_str: str,
        history: List[Dict[str, Any]],
        error_context: Optional[str] = None,
    ) -> Action:
        """
        Synchronous wrapper for testing/fallback.
        Note: Prefer async ainvoke() in production.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.ainvoke(goal, page_context_str, history, error_context)
        )


# Global singleton instance
_reasoning_chain: Optional[ReasoningChain] = None


def get_reasoning_chain(temperature: float = 0.1) -> ReasoningChain:
    """Get or create the global reasoning chain instance."""
    global _reasoning_chain
    if _reasoning_chain is None:
        _reasoning_chain = ReasoningChain(temperature=temperature)
    return _reasoning_chain


async def reason_with_chain(
    goal: str,
    page_context_str: str,
    history: List[Dict[str, Any]],
    error_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async helper to call reasoning chain and convert result to dict.

    This is the primary interface for the langgraph_runner.
    """
    chain = get_reasoning_chain()
    action = await chain.ainvoke(goal, page_context_str, history, error_context)

    # Convert Pydantic model to dict
    return action.model_dump(exclude_none=True)
