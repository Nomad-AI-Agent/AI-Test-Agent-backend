from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from story_spec.agents.llm_client import create_client, RateLimitError, message_content_to_text
from story_spec.core import tracing
from story_spec.core.models import TestRun, StepStatus

SYSTEM_PROMPT = """You are a QA lead writing a concise test run summary for a developer.

Write in plain English. Be direct. Do not use bullet points or headers.

The final verdict provided to you is authoritative. Do not contradict it.
If the final verdict is PASS, do not say "the test failed" even if some intermediate steps had transient failures that were later recovered.
If the final verdict is FAIL, explain the most important failure clearly.

Structure your response in exactly 3 short paragraphs:
1. Overall result (pass/fail) and what the test was checking
2. What specifically passed or failed, with the most important finding first
3. If there were failures: the most likely root cause and a suggested fix. If all passed: a one-line confirmation.

Keep the total response under 150 words.
"""


def _classify_failure(run: TestRun) -> str:
    if run.overall_status != StepStatus.FAIL:
        return "none"

    scroll_count = sum(1 for r in run.results if r.step.action.value == "scroll")
    for result in reversed(run.results):
        error = (result.error or "").lower()
        if "element not found" in error and scroll_count >= 3:
            return "missing_entity_after_search"
    return "generic_failure"


def generate_summary(run: TestRun, run_id: Optional[str] = None) -> str:
    """Use OpenRouter to write a plain-English summary of a completed test run."""

    passed = [r for r in run.results if r.status == StepStatus.PASS]
    failed = [r for r in run.results if r.status == StepStatus.FAIL]
    skipped = [r for r in run.results if r.status == StepStatus.SKIP]
    overall_status = run.overall_status.value.upper()
    recovered_failures = len(failed) if run.overall_status == StepStatus.PASS else 0
    failure_classification = _classify_failure(run)

    steps_detail = []
    for r in run.results:
        line = f"  Step {r.step.index+1} [{r.status.value.upper()}]: {r.step.description}"
        if r.error:
            line += f"\n    Error: {r.error}"
        steps_detail.append(line)

    user_prompt = f"""Test run details:
Final verdict: {overall_status}
URL: {run.url}
User story: {run.story}
Duration: {run.total_duration_ms}ms
Results: {len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped
Recovered transient failures: {recovered_failures}
Failure classification: {failure_classification}

Step-by-step results:
{chr(10).join(steps_detail)}

Write the summary now.

Important:
- Your first paragraph must agree with the final verdict: {overall_status}.
- If final verdict is PASS, describe failed intermediate steps as transient or recovered attempts, not as the overall outcome.
- If final verdict is FAIL, identify the most important unresolved failure.
- If failure classification is missing_entity_after_search, explain that the requested item likely does not exist or was not present in the loaded list view, and avoid blaming selectors unless the evidence clearly shows a selector bug."""

    import time

    client = create_client(temperature=0.3)
    response = None
    run_id = run_id or run.id
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    request_config = tracing.runnable_config(
        "run-summary",
        run_id=run_id,
        tags=["reporter"],
        metadata={"overall_status": overall_status, "failure_classification": failure_classification},
    )

    with tracing.trace_context(
        tags=["reporter"],
        metadata={
            "test_run_id": run_id,
            "overall_status": overall_status,
            "failure_classification": failure_classification,
        },
    ):
        for attempt in range(3):
            try:
                response = client.invoke(messages, config=request_config)
                return message_content_to_text(response.content).strip()
            except RateLimitError:
                if attempt < 2:
                    import click
                    click.echo(click.style(f"  [!] Rate limit reached. Waiting 45s for retry ({attempt+1}/2)...", fg="yellow"))
                    time.sleep(45)
                else:
                    raise
    if response is None:
        raise RuntimeError("OpenRouter did not return a response for the summary step.")
    return message_content_to_text(response.content).strip()
