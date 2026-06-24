"""
Agentic test runner: orchestrates the step-by-step LLM-driven browser loop.

Flow: Navigate -> Observe page -> Ask LLM for next action -> Execute -> Repeat
"""

import asyncio
import json
import re
import shutil
import uuid
import time
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any, TypedDict
from langgraph.graph import END, StateGraph
from story_spec.core.models import TestRun, StepResult, TestStep, StepStatus
from story_spec.core import storage
from story_spec.agents import parser
from story_spec.agents import browser
from story_spec.agents import analyzer
from story_spec.agents import reporter
from story_spec.core import config
from story_spec.core import supabase
from story_spec.core import tracing

ProgressCallback = Callable[[str, int, int, TestStep, StepResult], None]
CancelCallback = Callable[[], bool]
CancelReasonCallback = Callable[[], Optional[str]]
PauseCallback = Callable[[], bool]
PauseReasonCallback = Callable[[], Optional[str]]

MAX_STEPS = 25
HIGH_IMPACT_KEYWORDS = {
    "create", "save", "submit", "confirm", "delete", "remove", "finish",
    "complete", "continue", "next", "login", "log in", "sign in", "checkout",
    "place order", "pay", "purchase", "send", "invite", "publish",
}
ERROR_HINTS = {
    "error", "failed", "invalid", "required", "try again", "incorrect",
    "already exists", "unable", "problem", "issue", "missing",
}
SUCCESS_HINTS = {
    "success", "successfully", "created", "saved", "completed", "welcome",
    "dashboard", "overview", "confirmed", "done",
}
AUTHENTICATION_REQUEST_HINTS = {
    "log in with", "login with", "sign in with", "authenticate with",
    "log into", "log in to", "login to", "logs in", "sign into",
    "sign in to", "signs in", "log in and", "sign in and",
    "enter credentials", "use credentials", "using credentials",
    "type email", "type the email", "enter email", "type password",
    "type the password", "enter password",
}
LOGIN_PAGE_HINTS = {
    "login", "log in", "sign in", "signin", "email", "password",
}
LOGIN_SUBMIT_HINTS = {
    "login", "log in", "sign in", "signin", "submit",
}
MAX_SEARCH_SCROLLS = 6


class AgentGraphState(TypedDict, total=False):
    history: List[Dict[str, Any]]
    step_index: int
    consecutive_failures: int
    context: Dict[str, Any]
    context_str: str
    decision: Dict[str, Any]
    stop: bool


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return default


def create_run(url: str, story: str, run_id: Optional[str] = None) -> TestRun:
    return TestRun(
        id=run_id or str(uuid.uuid4()),
        url=url,
        story=story,
    )


def _infer_goal_status_from_results(run: TestRun) -> Optional[bool]:
    """
    Infer the final run verdict when the LLM never returns an explicit `done`.

    Only called once a run has actually finished — not while paused or mid-run.
    """
    if any(result.status == StepStatus.FAIL for result in run.results):
        return False
    if run.results and all(result.status == StepStatus.PASS for result in run.results):
        return True
    return None


def _contains_any(text: str, keywords: set[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _story_expects_auth_redirect(story: str) -> bool:
    lowered = (story or "").lower()
    if _contains_any(lowered, AUTHENTICATION_REQUEST_HINTS):
        return False

    has_auth_gate = _contains_any(
        lowered,
        {"not authorized", "unauthorized", "not authenticated", "unauthenticated"},
    )
    has_login_destination = _contains_any(
        lowered,
        {"login page", "sign in page", "signin page"},
    )
    has_redirect = _contains_any(lowered, {"redirect", "redirected"})
    return has_auth_gate or (has_redirect and has_login_destination)


def _context_text(context: Dict[str, Any]) -> str:
    return " ".join([
        context.get("url", ""),
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ])


def _context_has_login_form(context: Dict[str, Any]) -> bool:
    input_text = " ".join(
        " ".join(
            str(item.get(key, ""))
            for key in ("type", "name", "id", "placeholder", "label", "aria_label")
        )
        for item in context.get("inputs", [])
    )
    lowered = input_text.lower()
    has_identity_input = any(word in lowered for word in ("email", "username", "phone"))
    has_password_input = any(
        (item.get("type") or "").lower() == "password"
        or "password" in " ".join(str(item.get(key, "")) for key in ("name", "id", "placeholder", "label", "aria_label")).lower()
        for item in context.get("inputs", [])
    )
    return has_identity_input or has_password_input


def _context_is_login_page(context: Dict[str, Any]) -> bool:
    text = _context_text(context)
    url_or_title = " ".join([context.get("url", ""), context.get("title", "")])
    if _contains_any(url_or_title, {"login", "signin", "sign-in", "checkpoint"}):
        return True
    if _context_has_login_form(context) and _contains_any(text, LOGIN_PAGE_HINTS):
        return True
    return False


def _decision_attempts_login_form(decision: Dict[str, Any], context: Dict[str, Any]) -> bool:
    action = decision.get("action")
    decision_text = _decision_text(
        action or "",
        decision.get("target"),
        decision.get("value"),
        decision.get("description", ""),
    )
    if action == "type" and _contains_any(decision_text, {"email", "username", "phone", "password"}):
        return True
    if action == "click" and _context_has_login_form(context):
        return _contains_any(decision_text, LOGIN_SUBMIT_HINTS)
    return False


def _coerce_auth_redirect_decision(
    decision: Dict[str, Any],
    story: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    if not _story_expects_auth_redirect(story):
        return decision
    if not _context_is_login_page(context) and not _decision_attempts_login_form(decision, context):
        return decision

    return {
        "thought": "The story only requires confirming that an unauthorized user reaches the login page.",
        "action": "done",
        "description": "Goal achieved: unauthorized access redirected the user to the login page.",
        "success": True,
    }


def _decision_text(action: str, target: Optional[str], value: Optional[str], description: str) -> str:
    return " ".join(part for part in [action, target or "", value or "", description or ""] if part)


def _is_high_impact_action(action: str, target: Optional[str], value: Optional[str], description: str) -> bool:
    if action not in {"click", "select"}:
        return False
    return _contains_any(_decision_text(action, target, value, description), HIGH_IMPACT_KEYWORDS)


def _same_decision(decision: Dict[str, Any], history_item: Dict[str, Any]) -> bool:
    return (
        decision.get("action") == history_item.get("action")
        and (decision.get("target") or None) == (history_item.get("target") or None)
        and (decision.get("value") or None) == (history_item.get("value") or None)
    )


def _was_successfully_done_before(decision: Dict[str, Any], history: List[Dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("success") and _same_decision(decision, item):
            return True
    return False


def _selector_still_visible(context: Dict[str, Any], selector: Optional[str]) -> bool:
    if not selector:
        return False
    for key in ("inputs", "checkables", "buttons", "links"):
        for item in context.get(key, []):
            if item.get("selector") == selector:
                return True
    return False


def _page_has_error_signal(context: Dict[str, Any]) -> bool:
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(_contains_any(text, ERROR_HINTS) for text in haystacks)


def _page_has_success_signal(context: Dict[str, Any]) -> bool:
    haystacks = [
        context.get("title", ""),
        context.get("visible_text", ""),
        " ".join(h.get("text", "") for h in context.get("headings", [])),
    ]
    return any(_contains_any(text, SUCCESS_HINTS) for text in haystacks)


def _recent_consecutive_action_count(history: List[Dict[str, Any]], action: str) -> int:
    count = 0
    for item in reversed(history):
        if item.get("action") != action or not item.get("success"):
            break
        count += 1
    return count


def _extract_entity_name(text: str) -> Optional[str]:
    if not text:
        return None
    quoted = re.search(r"'([^']+)'|\"([^\"]+)\"", text)
    if quoted:
        return quoted.group(1) or quoted.group(2)
    match = re.search(r"for the ([^.]+?)(?: organization| link| page| details)?$", text.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _recent_missing_entity_failure(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    recent_scrolls = _recent_consecutive_action_count(history, "scroll")
    if recent_scrolls < 3:
        return None

    for item in reversed(history):
        if item.get("action") == "scroll" and item.get("success"):
            continue
        if (
            item.get("action") in {"click", "select"}
            and not item.get("success")
            and "element not found" in (item.get("error") or "").lower()
        ):
            return item
        break
    return None


def _coerce_exhausted_search_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    recent_scrolls = _recent_consecutive_action_count(history, "scroll")

    missing_item_failure = _recent_missing_entity_failure(history)
    if missing_item_failure and decision.get("action") in {"scroll", "wait", "screenshot"}:
        entity_name = _extract_entity_name(missing_item_failure.get("description", ""))
        target_text = entity_name or "the requested item"
        return {
            "thought": f"After repeated search attempts, {target_text} still is not present in the UI.",
            "action": "done",
            "description": f"Goal failed: {target_text} was not found after repeated search attempts.",
            "success": False,
        }

    if decision.get("action") == "scroll" and recent_scrolls >= MAX_SEARCH_SCROLLS:
        return {
            "thought": "Repeated scrolling has not revealed the requested item, so continuing is unlikely to help.",
            "action": "done",
            "description": "Goal failed: the requested item was not found after repeated scrolling/search attempts.",
            "success": False,
        }

    return decision


def _coerce_duplicate_high_impact_decision(
    decision: Dict[str, Any],
    history: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    action = decision.get("action", "screenshot")
    target = decision.get("target")
    value = decision.get("value")
    description = decision.get("description", "")

    if not _is_high_impact_action(action, target, value, description):
        return decision
    if not _was_successfully_done_before(decision, history):
        return decision

    if _page_has_error_signal(context):
        return {
            "thought": "The same high-impact action already succeeded once and the page now shows validation or error feedback.",
            "action": "screenshot",
            "description": "Capture page state after validation or error feedback",
        }

    if _page_has_success_signal(context) or not _selector_still_visible(context, target):
        return {
            "thought": "The same irreversible action already succeeded once and the page now indicates the workflow likely completed.",
            "action": "done",
            "description": f"Goal achieved after {description or action}",
            "success": True,
        }

    return {
        "thought": "The same irreversible action already succeeded once. Wait for the UI to settle before taking another step.",
        "action": "wait",
        "value": "1200",
        "description": "Wait for the page to settle after a successful submission",
    }


async def _handle_video(
    session: browser.BrowserSession,
    run: TestRun,
    videos_dir: Path,
) -> None:
    """Rename the recorded video to {run.id}.webm and upload to Supabase / save locally."""
    raw_path = session.video_path
    if not raw_path:
        return

    raw = Path(raw_path)
    if not raw.exists():
        return

    target_name = f"{run.id}.webm"
    target_path = videos_dir / target_name

    try:
        shutil.move(str(raw), str(target_path))
    except OSError:
        return

    video_bytes = target_path.read_bytes()

    public_url = await asyncio.to_thread(supabase.upload_video, run.id, target_name, video_bytes)
    if public_url:
        run.video_path = public_url
    else:
        run.video_path = str(target_path)
    storage.save_run(run)


async def execute(
    url: str,
    story: str,
    headless: bool = True,
    on_progress: Optional[ProgressCallback] = None,
    run_id: Optional[str] = None,
    should_cancel: Optional[CancelCallback] = None,
    cancel_reason: Optional[CancelReasonCallback] = None,
    should_pause: Optional[PauseCallback] = None,
    pause_reason: Optional[PauseReasonCallback] = None,
    resume_from_checkpoint: Optional[Dict] = None,
) -> TestRun:
    """Full agentic pipeline: navigate -> observe -> decide -> act -> repeat."""

    if resume_from_checkpoint and run_id:
        run = storage.load_run(run_id) or create_run(url, story, run_id)
        run.paused = False
        run.goal_achieved = None
        run.pause_checkpoint = None
    else:
        run = create_run(url, story, run_id)
    storage.save_run(run)

    history: List[Dict] = []
    step_index = 0
    total_start = time.time()
    if resume_from_checkpoint:
        prior_ms = resume_from_checkpoint.get("total_duration_ms", 0)
        if prior_ms:
            total_start = time.time() - (prior_ms / 1000)

    def cancellation_requested() -> bool:
        return should_cancel() if should_cancel else False

    def current_cancel_reason() -> str:
        if cancel_reason:
            reason = cancel_reason()
            if reason:
                return reason
        return "Run canceled by user."

    def cancel_run(reason: Optional[str] = None) -> None:
        run.canceled = True
        run.cancel_reason = reason or current_cancel_reason()
        run.goal_achieved = None
        run.total_duration_ms = int((time.time() - total_start) * 1000)
        storage.save_run(run)

    def pause_requested() -> bool:
        return should_pause() if should_pause else False

    def current_pause_reason() -> str:
        if pause_reason:
            reason = pause_reason()
            if reason:
                return reason
        return "Run paused by user."

    async def pause_run(
        page,
        *,
        current_step_index: Optional[int] = None,
        current_history: Optional[List[Dict]] = None,
    ) -> None:
        checkpoint_step_index = current_step_index if current_step_index is not None else step_index
        checkpoint_history = current_history if current_history is not None else history
        run.paused = True
        run.pause_checkpoint = {
            "step_index": checkpoint_step_index,
            "history": checkpoint_history,
            "page_url": page.url,
            "page_context": await analyzer.get_page_context(page),
            "cookies": await page.context.cookies(),
            "local_storage": await page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            ),
            "total_duration_ms": int((time.time() - total_start) * 1000),
            "timestamp": time.time(),
        }
        run.total_duration_ms = run.pause_checkpoint["total_duration_ms"]
        storage.save_run(run)

    videos_dir = config.VIDEOS_DIR / run.id
    session = browser.BrowserSession(headless=headless, videos_dir=videos_dir)

    try:
        await session.start()
        page = session.require_page()

        screenshot_dir = config.SCREENSHOTS_DIR / run.id
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # Resume from checkpoint if provided
        if resume_from_checkpoint:
            step_index = resume_from_checkpoint["step_index"]
            history = list(resume_from_checkpoint["history"])

            if resume_from_checkpoint.get("cookies"):
                await page.context.add_cookies(resume_from_checkpoint["cookies"])

            await page.goto(resume_from_checkpoint["page_url"])

            local_storage = resume_from_checkpoint.get("local_storage")
            if local_storage:
                if isinstance(local_storage, str):
                    local_storage = json.loads(local_storage)
                await page.evaluate(
                    "(data) => { localStorage.clear(); Object.entries(data).forEach(([k,v]) => localStorage.setItem(k,v)); }",
                    local_storage,
                )

            await asyncio.sleep(1)

        if cancellation_requested():
            cancel_run()
            raise asyncio.CancelledError

        if pause_requested():
            await pause_run(page)
            return run

        # Step 0: Navigate to the initial URL (only if not resuming)
        if not resume_from_checkpoint:
            result = await browser.execute_action(
                page=page,
                action="navigate",
                target=url,
                value=None,
                description=f"Navigate to {url}",
                screenshot_dir=screenshot_dir,
                step_index=step_index,
            )

            run.steps.append(result.step)
            run.results.append(result)
            history.append({
                "action": "navigate",
                "description": f"Navigate to {url}",
                "success": result.status == StepStatus.PASS,
                "error": result.error,
            })

            if on_progress:
                on_progress(run.id, step_index, MAX_STEPS, result.step, result)

            step_index += 1

        max_consecutive_failures = 3

        async def observe_node(state: AgentGraphState) -> AgentGraphState:
            if cancellation_requested():
                cancel_run()
                return {"stop": True}

            if pause_requested():
                await pause_run(
                    page,
                    current_step_index=state.get("step_index", step_index),
                    current_history=state.get("history", history),
                )
                return {"stop": True}

            context = {}
            try:
                context = await analyzer.get_page_context(page)
                context_str = analyzer.format_page_context(context)
            except Exception as e:
                context_str = f"URL: {page.url}\nError extracting page context: {str(e)}"
            return {"context": context, "context_str": context_str}

        async def decide_node(state: AgentGraphState) -> AgentGraphState:
            if state.get("stop"):
                return {}

            if pause_requested():
                await pause_run(
                    page,
                    current_step_index=state.get("step_index", step_index),
                    current_history=state.get("history", history),
                )
                return {"stop": True}

            context = state.get("context", {})
            context_str = state.get("context_str", "")
            state_history = state.get("history", [])
            last_error = None
            if run.results and run.results[-1].status == StepStatus.FAIL:
                last_error = run.results[-1].error

            try:
                decision = await asyncio.to_thread(
                    parser.decide_next_action,
                    goal=story,
                    page_context_str=context_str,
                    history=state_history,
                    error_context=last_error,
                    run_id=run.id,
                )
            except Exception as e:
                # LLM call failed — take a screenshot and continue
                error_text = str(e).strip() or e.__class__.__name__
                decision = {
                    "thought": f"LLM error: {error_text}",
                    "action": "screenshot",
                    "description": f"Screenshot (LLM call failed: {error_text[:120]})",
                }

            decision = _coerce_auth_redirect_decision(decision, story, context)
            decision = _coerce_duplicate_high_impact_decision(decision, state_history, context)
            decision = _coerce_exhausted_search_decision(decision, state_history)
            return {"decision": decision}

        async def finish_node(state: AgentGraphState) -> AgentGraphState:
            if cancellation_requested():
                cancel_run()
                return {"stop": True}

            if pause_requested():
                await pause_run(
                    page,
                    current_step_index=state.get("step_index", step_index),
                    current_history=state.get("history", history),
                )
                return {"stop": True}

            state_step_index = state.get("step_index", 0)
            decision = state.get("decision", {})
            final_result = await browser.execute_action(
                page=page,
                action="done",
                target=None,
                value=None,
                description=decision.get("description", "Goal assessment complete"),
                screenshot_dir=screenshot_dir,
                step_index=state_step_index,
            )
            run.steps.append(final_result.step)
            run.results.append(final_result)
            run.goal_achieved = _as_bool(decision.get("success"), default=False)

            if on_progress:
                on_progress(run.id, state_step_index, state_step_index + 1, final_result.step, final_result)

            return {"stop": True}

        async def act_node(state: AgentGraphState) -> AgentGraphState:
            if cancellation_requested():
                cancel_run()
                return {"stop": True}

            if pause_requested():
                await pause_run(
                    page,
                    current_step_index=state.get("step_index", 0),
                    current_history=state.get("history", history),
                )
                return {"stop": True}

            decision = state.get("decision", {})
            step_index = state.get("step_index", 0)
            action = decision.get("action", "screenshot")
            target = decision.get("target")
            value = decision.get("value")
            description = decision.get("description", f"Step {step_index + 1}")

            result = await browser.execute_action(
                page=page,
                action=action,
                target=target,
                value=value,
                description=description,
                screenshot_dir=screenshot_dir,
                step_index=step_index,
            )

            run.steps.append(result.step)
            run.results.append(result)
            state_history = state.get("history", [])
            state_history.append({
                "action": action,
                "target": target,
                "value": value,
                "description": description,
                "success": result.status == StepStatus.PASS,
                "error": result.error,
            })

            if on_progress:
                on_progress(run.id, step_index, MAX_STEPS, result.step, result)

            consecutive_failures = state.get("consecutive_failures", 0)
            stop = False
            if result.status == StepStatus.FAIL:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    run.goal_achieved = False
                    stop = True
            else:
                consecutive_failures = 0

            step_index += 1
            await asyncio.sleep(0.3)
            if step_index >= MAX_STEPS:
                stop = True

            return {
                "history": state_history,
                "step_index": step_index,
                "consecutive_failures": consecutive_failures,
                "stop": stop,
            }

        def route_after_observe(state: AgentGraphState) -> str:
            return END if state.get("stop") else "decide"

        def route_after_decide(state: AgentGraphState) -> str:
            if state.get("stop"):
                return END
            if cancellation_requested():
                cancel_run()
                return END
            decision = state.get("decision", {})
            if decision.get("action") == "done" or decision.get("done", False):
                return "finish"
            return "act"

        def route_after_act(state: AgentGraphState) -> str:
            return END if state.get("stop") else "observe"

        graph = StateGraph(AgentGraphState)
        graph.add_node("observe", observe_node)
        graph.add_node("decide", decide_node)
        graph.add_node("finish", finish_node)
        graph.add_node("act", act_node)
        graph.set_entry_point("observe")
        graph.add_conditional_edges("observe", route_after_observe, {"decide": "decide", END: END})
        graph.add_conditional_edges("decide", route_after_decide, {"finish": "finish", "act": "act", END: END})
        graph.add_edge("finish", END)
        graph.add_conditional_edges("act", route_after_act, {"observe": "observe", END: END})

        graph_config = tracing.runnable_config(
            "story-run-graph",
            run_id=run.id,
            tags=["graph"],
            metadata={"url": url, "story_length": len(story)},
        )
        graph_config["recursion_limit"] = MAX_STEPS * 4

        with tracing.trace_context(
            tags=["graph"],
            metadata={"test_run_id": run.id, "url": url, "story_length": len(story)},
        ):
            final_state = await graph.compile().ainvoke(
                {
                    "history": history,
                    "step_index": step_index,
                    "consecutive_failures": 0,
                    "stop": False,
                },
                graph_config,
            )
        step_index = final_state.get("step_index", step_index)

        if not run.canceled and not run.paused and run.goal_achieved is None:
            if step_index >= MAX_STEPS:
                run.goal_achieved = _infer_goal_status_from_results(run)

        if not run.canceled and not run.paused:
            run.total_duration_ms = int((time.time() - total_start) * 1000)
            storage.save_run(run)

    except asyncio.CancelledError:
        cancel_run()

    finally:
        await session.stop()
        # Handle video recording — rename and upload
        await _handle_video(session, run, videos_dir)

    if not run.canceled and cancellation_requested():
        cancel_run()

    if run.canceled:
        completed_steps = len(run.results)
        run.summary = f"Run canceled after {completed_steps} completed step{'s' if completed_steps != 1 else ''}. {run.cancel_reason or 'Run canceled by user.'}"
    elif run.paused:
        completed_steps = len(run.results)
        run.summary = f"Run paused after {completed_steps} completed step{'s' if completed_steps != 1 else ''}. State saved for resume."
    else:
        try:
            run.summary = await asyncio.to_thread(reporter.generate_summary, run, run.id)
        except asyncio.CancelledError:
            cancel_run()
            completed_steps = len(run.results)
            run.summary = f"Run canceled after {completed_steps} completed step{'s' if completed_steps != 1 else ''}. {run.cancel_reason or 'Run canceled by user.'}"
    storage.save_run(run)

    return run
