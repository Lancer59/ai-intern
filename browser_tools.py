"""
Browser interaction tools powered by Playwright.

Gives the AI agent the ability to:
- Take screenshots of running web pages
- Capture browser console logs (errors, warnings, info)
- Read DOM content (full body or a specific CSS selector)
- Click an element and screenshot the result
- Capture failed network requests

Security: navigation is restricted to localhost/127.0.0.1 by default.
Set allow_external=True to permit external URLs.
"""

import asyncio
import base64
import json
import logging
from typing import Optional
from langchain_core.tools import tool

logger = logging.getLogger("browser_tools")

_LOCALHOST_PREFIXES = ("http://localhost", "https://localhost", "http://127.0.0.1", "https://127.0.0.1")
_TIMEOUT_MS = 30_000


def _check_url(url: str, allow_external: bool) -> None:
    if not allow_external and not any(url.startswith(p) for p in _LOCALHOST_PREFIXES):
        raise ValueError(
            f"Navigation to external URL '{url}' is blocked. "
            "Pass allow_external=True to permit it."
        )


async def _get_playwright():
    """Lazy import so the module loads even if playwright isn't installed yet."""
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        raise ImportError(
            "playwright is not installed. Run: pip install playwright && playwright install chromium"
        )


@tool
async def browser_screenshot(url: str, wait_for: str = "", full_page: bool = False, allow_external: bool = Flase) -> str:
    """Navigate to a URL and return a base64-encoded PNG screenshot.

    Only localhost/127.0.0.1 URLs are permitted unless allow_external=True.
    Use this to visually verify a frontend render after making code changes.

    :param url: The URL to navigate to (e.g. 'http://localhost:3000').
    :param wait_for: Optional CSS selector to wait for before capturing (e.g. '#app').
    :param full_page: If True, captures the full scrollable page. Default False.
    :param allow_external: Set True to allow non-localhost URLs.
    :return: Base64-encoded PNG string prefixed with 'data:image/png;base64,' or an error message.
    """
    try:
        _check_url(url, allow_external)
        async_playwright = await _get_playwright()
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="networkidle")
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=_TIMEOUT_MS)
                screenshot_bytes = await page.screenshot(full_page=full_page)
                b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                return f"data:image/png;base64,{b64}"
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"browser_screenshot failed: {e}")
        return f"Error: {e}"


@tool
async def browser_get_console_logs(url: str, wait_ms: int = 3000, allow_external: bool = False) -> str:
    """Navigate to a URL and capture all browser console output during page load.

    Returns a JSON array of console events. Use this to detect JavaScript errors
    or warnings after a frontend code change.

    :param url: The URL to navigate to.
    :param wait_ms: Milliseconds to observe after page load (default 3000).
    :param allow_external: Set True to allow non-localhost URLs.
    :return: JSON string — list of {level, text, location} objects, or an error message.
    """
    try:
        _check_url(url, allow_external)
        async_playwright = await _get_playwright()
        logs = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()

                def _on_console(msg):
                    logs.append({
                        "level": msg.type,
                        "text": msg.text,
                        "location": f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}",
                    })

                page.on("console", _on_console)
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="networkidle")
                await asyncio.sleep(wait_ms / 1000)
            finally:
                await browser.close()

        return json.dumps(logs, indent=2)
    except Exception as e:
        logger.error(f"browser_get_console_logs failed: {e}")
        return f"Error: {e}"


@tool
async def browser_get_dom(url: str, selector: str = "", allow_external: bool = False) -> str:
    """Navigate to a URL and return the HTML of a DOM element or the full body.

    Use this to verify that dynamic data is rendering correctly in the browser.
    Output is truncated at 20,000 characters to stay within context limits.

    :param url: The URL to navigate to.
    :param selector: CSS selector of the element to read. If empty, returns full body innerHTML.
    :param allow_external: Set True to allow non-localhost URLs.
    :return: HTML string of the matched element or body, or an error message.
    """
    try:
        _check_url(url, allow_external)
        async_playwright = await _get_playwright()

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="networkidle")

                if selector:
                    await page.wait_for_selector(selector, timeout=_TIMEOUT_MS)
                    html = await page.eval_on_selector(selector, "el => el.outerHTML")
                else:
                    html = await page.evaluate("() => document.body.innerHTML")
            finally:
                await browser.close()

        max_chars = 20_000
        if len(html) > max_chars:
            html = html[:max_chars] + f"\n\n... [truncated at {max_chars} characters]"
        return html
    except Exception as e:
        logger.error(f"browser_get_dom failed: {e}")
        return f"Error: {e}"


@tool
async def browser_click_and_screenshot(
    url: str,
    selector: str,
    wait_for: str = "",
    allow_external: bool = False,
) -> str:
    """Navigate to a URL, click an element, and return a screenshot of the result.

    Use this to test interactive UI flows (e.g. clicking a button and verifying
    the resulting state renders correctly).

    :param url: The URL to navigate to.
    :param selector: CSS selector of the element to click.
    :param wait_for: Optional CSS selector to wait for after the click.
    :param allow_external: Set True to allow non-localhost URLs.
    :return: Base64-encoded PNG string or an error message.
    """
    try:
        _check_url(url, allow_external)
        async_playwright = await _get_playwright()

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="networkidle")
                await page.wait_for_selector(selector, timeout=_TIMEOUT_MS)
                await page.click(selector)
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=_TIMEOUT_MS)
                else:
                    await page.wait_for_load_state("networkidle", timeout=_TIMEOUT_MS)
                screenshot_bytes = await page.screenshot()
                b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                return f"data:image/png;base64,{b64}"
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"browser_click_and_screenshot failed: {e}")
        return f"Error: {e}"


@tool
async def browser_get_network_errors(url: str, wait_ms: int = 5000, allow_external: bool = False) -> str:
    """Navigate to a URL and capture all failed or errored network requests.

    Returns HTTP 4xx/5xx responses and requests that failed entirely (e.g. DNS errors).
    Use this to diagnose broken API calls or missing static assets.

    :param url: The URL to navigate to.
    :param wait_ms: Milliseconds to observe after page load (default 5000).
    :param allow_external: Set True to allow non-localhost URLs.
    :return: JSON string — list of {url, status, method} objects, or an error message.
    """
    try:
        _check_url(url, allow_external)
        async_playwright = await _get_playwright()
        errors = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()

                def _on_request_failed(request):
                    errors.append({
                        "url": request.url,
                        "status": None,
                        "method": request.method,
                        "failure": request.failure,
                    })

                async def _on_response(response):
                    if response.status >= 400:
                        errors.append({
                            "url": response.url,
                            "status": response.status,
                            "method": response.request.method,
                            "failure": None,
                        })

                page.on("requestfailed", _on_request_failed)
                page.on("response", _on_response)
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="networkidle")
                await asyncio.sleep(wait_ms / 1000)
            finally:
                await browser.close()

        return json.dumps(errors, indent=2)
    except Exception as e:
        logger.error(f"browser_get_network_errors failed: {e}")
        return f"Error: {e}"
