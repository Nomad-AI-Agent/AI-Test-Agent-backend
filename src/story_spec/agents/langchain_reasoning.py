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

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.pydantic_v1 import ValidationError

from story_spec.agents.action_schemas import Action, dict_to_action
from story_spec.agents.prompts import SYSTEM_PROMPT
from story_spec.agents.history_formatter import format_action_history
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
        history_text = format_action_history(history)
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
