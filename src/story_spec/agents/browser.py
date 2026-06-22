"""
Browser execution engine with smart element location.
Provides a BrowserSession for the agentic loop and smart fallback locators.
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Playwright
from playwright.async_api import TimeoutError as PWTimeout
from story_spec.core.models import TestStep, StepResult, StepStatus, ActionType
from story_spec.core import config
from story_spec.core import supabase

SELECTOR_TIMEOUT = 10000
NAV_TIMEOUT = 30000

POST_ACTION_SETTLE_MS = 600


def _normalize_url(url: Optional[str]) -> str:
    """Return a browser-ready URL, adding https:// when the scheme is omitted."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Navigation target is empty.")

    parsed = urlparse(raw)
    if parsed.scheme:
        return raw
    if raw.startswith("//"):
        return f"https:{raw}"
    return f"https://{raw}"


async def _page_has_usable_content(page: Page) -> bool:
    """
    Some public sites keep network work open or delay lifecycle events enough for
    Playwright to time out even though the DOM is usable. Treat those cases as
    successful navigation when the page has moved away from the blank document
    and contains visible content.
    """
    try:
        return await page.evaluate("""() => {
            const bodyText = document.body ? document.body.innerText.trim() : "";
            return window.location.href !== "about:blank"
                && document.readyState !== "loading"
                && bodyText.length > 0;
        }""")
    except Exception:
        return page.url != "about:blank"


def _require_target(target: Optional[str], action: str) -> str:
    if target:
        return target
    raise ValueError(f"{action} action requires a target selector.")




def _windows_default_browser_hint() -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except Exception:
        return None

    normalized = str(prog_id).lower()
    if "brave" in normalized:
        return "brave"
    if "microsoftedge" in normalized or "mseed" in normalized or "edge" in normalized:
        return "msedge"
    if "chrome" in normalized:
        return "chrome"
    if "firefox" in normalized:
        return "firefox"
    if "vivaldi" in normalized:
        return "vivaldi"
    if "opera" in normalized:
        return "opera"
    return None


def _infer_browser_launch(
    user_agent: Optional[str],
    browser_hint: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Pick a browser type/channel that best matches the client browser."""
    hint = (browser_hint or "").lower()
    ua = (user_agent or "").lower()
    combined = f"{hint} {ua}"

    if "brave" in combined:
        return "chromium", "brave"
    if "firefox/" in combined or "firefox" in hint:
        return "firefox", None
    if "vivaldi" in combined:
        return "chromium", "vivaldi"
    if "opr/" in combined or "opera" in combined:
        return "chromium", "opera"
    if "safari/" in ua and "chrome/" not in ua and "crios/" not in ua and "edg/" not in ua:
        return "webkit", None
    if "edg/" in combined or "edge" in hint:
        return "chromium", "msedge"
    if "chrome/" in combined or "chromium" in combined or "crios/" in combined:
        default_hint = _windows_default_browser_hint()
        if default_hint in {"brave", "vivaldi", "opera", "msedge", "chrome"}:
            return "chromium", default_hint
        return "chromium", "chrome"
    return "chromium", None


def _candidate_paths(*parts: str) -> list[Path]:
    paths: list[Path] = []
    for env_var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_var)
        if base:
            paths.append(Path(base, *parts))
    return paths


def _find_chromium_executable(channel: str) -> Optional[str]:
    """Return an installed Chromium-family executable for non-Playwright channels."""
    channel_paths = {
        "brave": _candidate_paths("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        "opera": _candidate_paths("Programs", "Opera", "opera.exe") + _candidate_paths("Opera", "launcher.exe"),
        "vivaldi": _candidate_paths("Vivaldi", "Application", "vivaldi.exe"),
    }
    for path in channel_paths.get(channel, []):
        if path.exists():
            return str(path)
    return None


class BrowserSession:
    """Manages a persistent browser session for the agentic loop."""

    def __init__(
        self,
        headless: bool = True,
        source_user_agent: Optional[str] = None,
        source_browser_hint: Optional[str] = None,
    ):
        self.headless = headless
        self.source_user_agent = source_user_agent
        self.source_browser_hint = source_browser_hint
        self._playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._owns_browser = True

    def _visible_launch_candidates(self) -> list[tuple[str, Optional[str]]]:
        candidates: list[tuple[str, Optional[str]]] = []
        browser_type, inferred_channel = _infer_browser_launch(self.source_user_agent, self.source_browser_hint)

        if browser_type in {"firefox", "webkit"}:
            candidates.append((browser_type, None))
        elif inferred_channel:
            candidates.append(("chromium", inferred_channel))

        for channel in ("brave", "msedge", "chrome", None):
            candidate = ("chromium", channel)
            if candidate not in candidates:
                candidates.append(candidate)

        if browser_type in {"firefox", "webkit"}:
            candidate = (browser_type, None)
            if candidate not in candidates:
                candidates.append(candidate)

        return candidates

    async def _launch_visible_context(self) -> BrowserContext:
        if self._playwright is None:
            raise RuntimeError("Playwright has not been started.")
        playwright = self._playwright

        profile_base = config.BASE_DIR / ".browser-profile"

        last_error: Optional[Exception] = None
        for browser_name, channel in self._visible_launch_candidates():
            profile_key = channel or browser_name
            profile_root = profile_base / profile_key
            profile_root.mkdir(parents=True, exist_ok=True)
            try:
                if browser_name == "firefox":
                    browser_type = playwright.firefox
                elif browser_name == "webkit":
                    browser_type = playwright.webkit
                else:
                    browser_type = playwright.chromium
                user_agent = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
                executable_path = _find_chromium_executable(channel) if channel else None
                if browser_name == "chromium" and executable_path:
                    context = await browser_type.launch_persistent_context(
                        str(profile_root),
                        headless=False,
                        executable_path=executable_path,
                        viewport={"width": 1280, "height": 800},
                        user_agent=user_agent,
                    )
                elif browser_name == "chromium" and channel in {"chrome", "msedge"}:
                    context = await browser_type.launch_persistent_context(
                        str(profile_root),
                        headless=False,
                        channel=channel,
                        viewport={"width": 1280, "height": 800},
                        user_agent=user_agent,
                    )
                elif browser_name == "chromium" and channel:
                    raise FileNotFoundError(f"Could not find executable for {channel}.")
                else:
                    context = await browser_type.launch_persistent_context(
                        str(profile_root),
                        headless=False,
                        viewport={"width": 1280, "height": 800},
                        user_agent=user_agent,
                    )
                self._owns_browser = True
                return context
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"Could not launch a visible browser session: {last_error}")

    async def start(self):
        playwright = await async_playwright().start()
        self._playwright = playwright
        if self.headless:
            self.browser = await playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
        else:
            self.context = await self._launch_visible_context()
            self.browser = self.context.browser
        self.page = await self.context.new_page()

    async def stop(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                if self.browser and self._owns_browser:
                    await self.browser.close()
        elif self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    def require_page(self) -> Page:
        """Return the active page after start(), or fail fast if startup did not complete."""
        if self.page is None:
            raise RuntimeError("Browser session has no active page. Call start() before using the session.")
        return self.page


async def smart_find(page: Page, selector: str, description: str = ""):
    """
    Try multiple strategies to find an element on the page.
    
    Priority:
    1. Exact CSS selector (from page context should work most of the time)
    2. Relaxed CSS selector variations
    3. Text/role/label-based Playwright locators (fallback)
    """

    # Strategy 1: Direct CSS selector
    if selector:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(timeout=SELECTOR_TIMEOUT, state="visible")
            return locator
        except (PWTimeout, Exception):
            pass

    # Strategy 2: If selector has complex path, try simpler versions
    if selector and ' > ' in selector:
        # Try just the last part of the path
        last_part = selector.split(' > ')[-1]
        try:
            locator = page.locator(last_part).first
            await locator.wait_for(timeout=3000, state="visible")
            return locator
        except (PWTimeout, Exception):
            pass

    # Strategy 3: Text-based fallback using the step description
    desc_lower = (description or "").lower()

    # For buttons, try get_by_role
    if any(word in desc_lower for word in ["button", "click", "submit", "login", "sign", "log in"]):
        button_keywords = [
            "login", "log in", "sign in", "signin", "submit", "register",
            "sign up", "signup", "continue", "next", "send", "ok", "confirm",
            "save", "create", "delete", "cancel", "close", "accept",
        ]
        for keyword in button_keywords:
            if keyword in desc_lower:
                try:
                    locator = page.get_by_role("button", name=keyword).first
                    await locator.wait_for(timeout=3000, state="visible")
                    return locator
                except (PWTimeout, Exception):
                    pass
                # Also try as a link that looks like a button
                try:
                    locator = page.get_by_role("link", name=keyword).first
                    await locator.wait_for(timeout=2000, state="visible")
                    return locator
                except (PWTimeout, Exception):
                    pass

    # For inputs, try get_by_label or get_by_placeholder
    input_keywords = {
        "email": ["email", "e-mail"],
        "password": ["password", "pass"],
        "username": ["username", "user name", "user"],
        "name": ["name", "full name", "first name", "last name"],
        "phone": ["phone", "mobile", "telephone"],
        "search": ["search"],
    }
    for field_type, keywords in input_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            # Try label
            try:
                locator = page.get_by_label(field_type, exact=False).first
                await locator.wait_for(timeout=2000, state="visible")
                return locator
            except (PWTimeout, Exception):
                pass
            # Try placeholder
            try:
                locator = page.get_by_placeholder(field_type, exact=False).first
                await locator.wait_for(timeout=2000, state="visible")
                return locator
            except (PWTimeout, Exception):
                pass

    # Strategy 4: Try get_by_text as a last resort for clickable elements
    if selector and not any(c in selector for c in ['#', '.', '[', '>']):
        # selector might actually be text content
        try:
            locator = page.get_by_text(selector, exact=False).first
            await locator.wait_for(timeout=2000, state="visible")
            return locator
        except (PWTimeout, Exception):
            pass

    raise PWTimeout(f"Could not find element: {selector} ({description})")


async def _settle_after_click(page: Page, description: str = ""):
    """
    Let the UI settle after clicks so the next planning cycle sees the updated
    page state instead of an in-flight form or navigation.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=3000)
    except PWTimeout:
        pass

    lowered = (description or "").lower()
    if any(keyword in lowered for keyword in ["create", "save", "submit", "login", "sign in", "continue", "next"]):
        await asyncio.sleep(1.2)
    else:
        await asyncio.sleep(POST_ACTION_SETTLE_MS / 1000)


async def execute_action(
    page: Page,
    action: str,
    target: Optional[str],
    value: Optional[str],
    description: str,
    screenshot_dir: Path,
    step_index: int,
) -> StepResult:
    """Execute a single browser action and return the result."""

    start = time.time()
    screenshot_path = None

    # Map action string to ActionType (handle "done" specially)
    try:
        action_type = ActionType(action) if action != "done" else ActionType.SCREENSHOT
    except ValueError:
        action_type = ActionType.SCREENSHOT

    step = TestStep(
        index=step_index,
        action=action_type,
        description=description,
        target=target,
        value=value,
    )

    async def take_screenshot(suffix=""):
        fname = f"step_{step_index:02d}{suffix}.png"
        # Take screenshot as bytes
        img_bytes = await page.screenshot(full_page=False)
        
        # Try uploading to Supabase
        run_id = screenshot_dir.name
        public_url = await asyncio.to_thread(supabase.upload_screenshot, run_id, fname, img_bytes)
        
        if public_url:
            return public_url
            
        # Fallback to local storage
        path = str(screenshot_dir / fname)
        with open(path, "wb") as f:
            f.write(img_bytes)
        return path

    try:
        if action == "navigate":
            navigation_target = _normalize_url(target)
            step.target = navigation_target
            navigation_timed_out = False
            try:
                await page.goto(navigation_target, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            except PWTimeout:
                navigation_timed_out = True
                if not await _page_has_usable_content(page):
                    raise

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PWTimeout:
                pass  # networkidle timeout is acceptable
            screenshot_path = await take_screenshot()
            if navigation_timed_out:
                step.description = f"{description} (page became usable before navigation fully settled)"

        elif action == "click":
            locator = await smart_find(page, _require_target(target, action), description)
            await locator.click()
            await _settle_after_click(page, description)
            screenshot_path = await take_screenshot()

        elif action == "type":
            locator = await smart_find(page, _require_target(target, action), description)
            await locator.fill(value or "")
            screenshot_path = await take_screenshot()

        elif action == "select":
            locator = await smart_find(page, _require_target(target, action), description)
            await locator.select_option(label=value)
            screenshot_path = await take_screenshot()

        elif action == "hover":
            locator = await smart_find(page, _require_target(target, action), description)
            await locator.hover()
            screenshot_path = await take_screenshot("_hover")

        elif action == "scroll":
            val = (value or "down").lower()
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

        elif action == "wait":
            ms = int(value or "1000")
            await asyncio.sleep(ms / 1000)

        elif action == "screenshot":
            screenshot_path = await take_screenshot("_manual")

        elif action == "done":
            screenshot_path = await take_screenshot("_final")

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
        if action == "navigate":
            error = f"Timeout while navigating to {target}"
        else:
            error = f"Timeout: element not found - {target}"
        return StepResult(
            step=step,
            status=StepStatus.FAIL,
            screenshot_path=screenshot_path,
            error=error,
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
            error=str(e)[:200],
            duration_ms=duration,
        )
