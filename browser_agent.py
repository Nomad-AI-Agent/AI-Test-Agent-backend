import asyncio
import time
from pathlib import Path
from typing import List, Callable, Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout
from models import TestStep, StepResult, StepStatus, ActionType, TestRun
import config


ProgressCallback = Callable[[int, TestStep, StepResult], None]

SELECTOR_TIMEOUT = 8000
NAV_TIMEOUT = 15000


async def _execute_step(page: Page, step: TestStep, screenshot_dir: Path) -> StepResult:
    start = time.time()
    screenshot_path = None

    async def take_screenshot(suffix=""):
        fname = f"step_{step.index:02d}{suffix}.png"
        path = str(screenshot_dir / fname)
        await page.screenshot(path=path, full_page=False)
        return path

    try:
        action = step.action

        if action == ActionType.NAVIGATE:
            await page.goto(step.target, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=5000)
            screenshot_path = await take_screenshot()

        elif action == ActionType.CLICK:
            await page.wait_for_selector(step.target, timeout=SELECTOR_TIMEOUT, state="visible")
            await page.click(step.target)
            screenshot_path = await take_screenshot()

        elif action == ActionType.TYPE:
            await page.wait_for_selector(step.target, timeout=SELECTOR_TIMEOUT, state="visible")
            await page.fill(step.target, step.value or "")
            screenshot_path = await take_screenshot()

        elif action == ActionType.ASSERT_TEXT:
            content = await page.content()
            text_visible = await page.evaluate(
                "(text) => document.body.innerText.includes(text)",
                step.assertion
            )
            if not text_visible:
                raise AssertionError(f"Expected text not found: '{step.assertion}'")
            screenshot_path = await take_screenshot("_assert")

        elif action == ActionType.ASSERT_URL:
            current_url = page.url
            if step.assertion not in current_url:
                raise AssertionError(
                    f"URL assertion failed. Expected '{step.assertion}' in '{current_url}'"
                )
            screenshot_path = await take_screenshot("_assert")

        elif action == ActionType.ASSERT_ELEMENT:
            await page.wait_for_selector(step.target, timeout=SELECTOR_TIMEOUT, state="visible")
            screenshot_path = await take_screenshot("_assert")

        elif action == ActionType.WAIT:
            ms = int(step.value or "1000")
            await asyncio.sleep(ms / 1000)

        elif action == ActionType.SCREENSHOT:
            screenshot_path = await take_screenshot("_manual")

        elif action == ActionType.SCROLL:
            val = (step.value or "down").lower()
            if val == "down":
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
            elif val == "up":
                await page.evaluate("window.scrollBy(0, -window.innerHeight)")
            else:
                try:
                    px = int(val)
                    await page.evaluate(f"window.scrollBy(0, {px})")
                except ValueError:
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
            screenshot_path = await take_screenshot("_scroll")

        elif action == ActionType.HOVER:
            await page.wait_for_selector(step.target, timeout=SELECTOR_TIMEOUT, state="visible")
            await page.hover(step.target)
            screenshot_path = await take_screenshot("_hover")

        elif action == ActionType.SELECT:
            await page.wait_for_selector(step.target, timeout=SELECTOR_TIMEOUT, state="visible")
            await page.select_option(step.target, label=step.value)
            screenshot_path = await take_screenshot()

        duration = int((time.time() - start) * 1000)
        return StepResult(
            step=step,
            status=StepStatus.PASS,
            screenshot_path=screenshot_path,
            duration_ms=duration,
        )

    except PWTimeout as e:
        duration = int((time.time() - start) * 1000)
        try:
            screenshot_path = await take_screenshot("_fail")
        except Exception:
            pass
        return StepResult(
            step=step,
            status=StepStatus.FAIL,
            screenshot_path=screenshot_path,
            error=f"Timeout: element not found — {step.target}",
            duration_ms=duration,
        )

    except AssertionError as e:
        duration = int((time.time() - start) * 1000)
        try:
            screenshot_path = await take_screenshot("_fail")
        except Exception:
            pass
        return StepResult(
            step=step,
            status=StepStatus.FAIL,
            screenshot_path=screenshot_path,
            error=str(e),
            duration_ms=duration,
        )

    except Exception as e:
        duration = int((time.time() - start) * 1000)
        try:
            screenshot_path = await take_screenshot("_fail")
        except Exception:
            pass
        return StepResult(
            step=step,
            status=StepStatus.FAIL,
            screenshot_path=screenshot_path,
            error=str(e),
            duration_ms=duration,
        )


async def run_steps(
    run: TestRun,
    on_progress: Optional[ProgressCallback] = None,
    headless: bool = True,
) -> List[StepResult]:
    """Execute all test steps in a Playwright browser session."""

    screenshot_dir = config.SCREENSHOTS_DIR / run.id
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    results: List[StepResult] = []
    total_start = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        stop_on_fail = False

        for i, step in enumerate(run.steps):
            if stop_on_fail and results and results[-1].status == StepStatus.FAIL:
                result = StepResult(
                    step=step,
                    status=StepStatus.SKIP,
                    error="Skipped due to previous failure",
                )
                results.append(result)
                if on_progress:
                    on_progress(i, step, result)
                continue

            result = await _execute_step(page, step, screenshot_dir)
            results.append(result)

            if on_progress:
                on_progress(i, step, result)

        await browser.close()

    run.total_duration_ms = int((time.time() - total_start) * 1000)
    return results
