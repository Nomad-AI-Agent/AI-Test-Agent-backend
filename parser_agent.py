import json
import re
from typing import List
import groq
from models import TestStep, ActionType
import config

SYSTEM_PROMPT = """You are a senior QA engineer. Your job is to convert a plain-English user story into a precise, ordered list of browser test steps.

OUTPUT FORMAT: Respond with ONLY a valid JSON object. No explanation, no markdown, no code fences.

JSON schema:
{
  "steps": [
    {
      "action": "<one of the allowed actions>",
      "description": "<human-readable description of this step>",
      "target": "<CSS selector OR full URL — required for navigate/click/type/assert/hover/scroll/select>",
      "value": "<text to type, option value, or scroll amount — required for type/select/scroll>",
      "assertion": "<exact text or URL substring to verify — required for assert_text/assert_url>"
    }
  ]
}

ALLOWED ACTIONS:
- navigate    : go to a URL (target = full URL)
- click       : click an element (target = CSS selector)
- type        : type text into an input (target = CSS selector, value = text)
- assert_text : verify text is visible on page (assertion = expected text)
- assert_url  : verify current URL contains a substring (assertion = URL substring)
- assert_element : verify an element exists (target = CSS selector)
- wait        : pause for a moment (value = milliseconds as string, e.g. "1000")
- screenshot  : capture the current state (description only needed)
- scroll      : scroll the page (value = "down", "up", or pixel amount as string)
- hover       : hover over an element (target = CSS selector)
- select      : select a dropdown option (target = CSS selector, value = option text)

RULES:
1. Always start with a navigate step to the given URL
2. Add a screenshot step after every major action (login, form submit, navigation)
3. Use realistic CSS selectors: prefer input[type="email"], button[type="submit"], #id, [name="field"] over fragile nth-child selectors
4. If the story mentions login, always assert the post-login state (dashboard, welcome message, URL change)
5. Keep steps atomic — one action per step
6. Add wait steps (500-1000ms) after clicks that trigger page loads or animations
7. Generate between 5 and 20 steps depending on story complexity
"""


def parse_story(url: str, story: str) -> List[TestStep]:
    """Use Gemini to convert a user story into structured test steps."""

    client = groq.Groq(api_key=config.GROQ_API_KEY)

    user_prompt = f"""URL: {url}

User story: {story}

Generate the test steps now."""

    import time

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            break
        except groq.RateLimitError as e:
            if attempt < 2:
                import click
                click.echo(click.style(f"  [!] Rate limit reached. Waiting 45s for retry ({attempt+1}/2)...", fg="yellow"))
                time.sleep(45)
            else:
                raise

    raw = response.choices[0].message.content.strip()

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)
    steps_data = data.get("steps", [])

    steps = []
    for i, s in enumerate(steps_data):
        action_str = s.get("action", "").strip().lower()
        try:
            action = ActionType(action_str)
        except ValueError:
            action = ActionType.SCREENSHOT

        step = TestStep(
            index=i,
            action=action,
            description=s.get("description", f"Step {i+1}"),
            target=s.get("target"),
            value=s.get("value"),
            assertion=s.get("assertion"),
        )
        steps.append(step)

    return steps


def format_steps_preview(steps: List[TestStep]) -> str:
    """Return a readable preview of parsed steps for CLI output."""
    lines = []
    for s in steps:
        parts = [f"  [{s.index+1}] {s.action.value.upper():15} {s.description}"]
        if s.target:
            parts.append(f"        target    : {s.target}")
        if s.value:
            parts.append(f"        value     : {s.value}")
        if s.assertion:
            parts.append(f"        assertion : {s.assertion}")
        lines.append("\n".join(parts))
    return "\n".join(lines)
