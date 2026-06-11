"""
Agentic brain: decides the next action based on the current page state.
Instead of generating all steps upfront, this module is called in a loop —
each call sees the live page context and decides ONE action at a time.
"""

import json
import re
import time
from json import JSONDecodeError
from typing import List, Optional, Dict
from story_spec.agents.llm_client import create_client, RateLimitError, BadRequestError
from story_spec.core.models import ActionType
from story_spec.core import config

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(fn):
            return fn
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

RESPOND with ONLY a valid JSON object. No explanation, no markdown, no code fences.

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
  "description": "Goal achieved: <what was accomplished> OR Goal failed: <why it failed>",
  "success": true or false
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


def _extract_json_object(raw: str) -> Optional[Dict]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            candidate, _ = decoder.raw_decode(raw[match.start():])
        except JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None



@traceable(name="decide_next_action", run_type="llm")
def decide_next_action(
    goal: str,
    page_context_str: str,
    history: List[Dict],
    error_context: Optional[str] = None,
) -> Dict:
    """Ask the LLM to decide the next action based on current page state."""

    client = create_client()

    # Build history text
    history_text = ""
    if history:
        history_lines = []
        for i, h in enumerate(history):
            status = "SUCCESS" if h.get("success") else "FAILED"
            line = f"  Step {i+1}: [{status}] {h['action'].upper()} - {h['description']}"
            if h.get("error"):
                line += f"\n    Error: {h['error']}"
            history_lines.append(line)
        history_text = "\n".join(history_lines)

    user_prompt = f"""GOAL: {goal}

=== CURRENT PAGE STATE ===
{page_context_str}
=== END PAGE STATE ===

{("ACTIONS TAKEN SO FAR:" + chr(10) + history_text) if history_text else "No actions taken yet. This is the starting page after initial navigation."}

{("LAST ACTION FAILED WITH ERROR: " + error_context) if error_context else ""}

Special guidance:
- Complete the user's requested outcome exactly once.
- Avoid duplicate creation of the same entity.
- If a checkbox/radio required by the story is already in the correct state, leave it unchanged.

What is the next action to take? Respond with ONLY a valid JSON object."""

    for attempt in range(3):
        try:
            request_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            try:
                response = client.chat.completions.create(
                    model=config.OPENROUTER_MODEL,
                    messages=request_messages,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            except BadRequestError as e:
                error_text = str(e).lower()
                if "response_format" not in error_text and "json_object" not in error_text:
                    raise

                response = client.chat.completions.create(
                    model=config.OPENROUTER_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT + "\nAlways return raw JSON only."},
                        {
                            "role": "user",
                            "content": user_prompt + "\n\nIMPORTANT: Return only valid JSON. No markdown. No explanation.",
                        },
                    ],
                    temperature=0.1,
                )
            break
        except RateLimitError:
            if attempt < 2:
                import click
                click.echo(click.style(
                    f"  [!] Rate limit reached. Waiting 45s for retry ({attempt+1}/2)...",
                    fg="yellow"
                ))
                time.sleep(45)
            else:
                raise

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise RuntimeError("OpenRouter returned empty content for the planning step.")

    # Clean any markdown wrapping
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is not None:
            return recovered

        return {
            "thought": f"Failed to parse LLM response: {raw[:200]}",
            "action": "wait",
            "value": "1200",
            "description": "Wait for next planning cycle (LLM response cleanup)",
        }
