from typing import List
import groq
from models import TestRun, StepResult, StepStatus
import config

SYSTEM_PROMPT = """You are a QA lead writing a concise test run summary for a developer.

Write in plain English. Be direct. Do not use bullet points or headers.

Structure your response in exactly 3 short paragraphs:
1. Overall result (pass/fail) and what the test was checking
2. What specifically passed or failed, with the most important finding first
3. If there were failures: the most likely root cause and a suggested fix. If all passed: a one-line confirmation.

Keep the total response under 150 words.
"""


def generate_summary(run: TestRun) -> str:
    """Use Groq to write a plain-English summary of a completed test run."""

    passed = [r for r in run.results if r.status == StepStatus.PASS]
    failed = [r for r in run.results if r.status == StepStatus.FAIL]
    skipped = [r for r in run.results if r.status == StepStatus.SKIP]

    steps_detail = []
    for r in run.results:
        line = f"  Step {r.step.index+1} [{r.status.value.upper()}]: {r.step.description}"
        if r.error:
            line += f"\n    Error: {r.error}"
        steps_detail.append(line)

    user_prompt = f"""Test run details:
URL: {run.url}
User story: {run.story}
Duration: {run.total_duration_ms}ms
Results: {len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped

Step-by-step results:
{chr(10).join(steps_detail)}

Write the summary now."""

    import time

    client = groq.Groq(api_key=config.GROQ_API_KEY)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except groq.RateLimitError as e:
            if attempt < 2:
                import click
                click.echo(click.style(f"  [!] Rate limit reached. Waiting 45s for retry ({attempt+1}/2)...", fg="yellow"))
                time.sleep(45)
            else:
                raise
    return response.choices[0].message.content.strip()
