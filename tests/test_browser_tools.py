"""Tests for tools/browser_tools.py

Browser tests that require a live browser are marked with @pytest.mark.browser
and skipped by default. Run them with: pytest -m browser
"""
import pytest
from tools.browser_tools import (
    _check_url,
    browser_screenshot,
    browser_get_console_logs,
    browser_get_dom,
    browser_get_network_errors,
    browser_click_and_screenshot,
)


# ---------------------------------------------------------------------------
# _check_url — pure logic, no browser needed
# ---------------------------------------------------------------------------

class TestCheckUrl:
    def test_localhost_always_allowed(self):
        # Should not raise
        _check_url("http://localhost:3000", allow_external=False)
        _check_url("http://127.0.0.1:8000", allow_external=False)
        _check_url("https://localhost", allow_external=False)

    def test_external_blocked_by_default(self):
        with pytest.raises(ValueError, match="blocked"):
            _check_url("https://example.com", allow_external=False)

    def test_external_allowed_when_flag_set(self):
        # Should not raise
        _check_url("https://example.com", allow_external=True)
        _check_url("https://github.com", allow_external=True)

    def test_non_http_external_blocked(self):
        with pytest.raises(ValueError):
            _check_url("ftp://example.com", allow_external=False)


# ---------------------------------------------------------------------------
# Tool error handling — no browser needed, just bad inputs
# ---------------------------------------------------------------------------

class TestBrowserToolErrorHandling:
    @pytest.mark.asyncio
    async def test_screenshot_invalid_url_returns_error(self):
        result = await browser_screenshot.ainvoke({
            "url": "http://localhost:1",   # nothing listening
            "allow_external": False,
        })
        assert result.startswith("Error")

    @pytest.mark.asyncio
    async def test_console_logs_invalid_url_returns_error(self):
        result = await browser_get_console_logs.ainvoke({
            "url": "http://localhost:1",
            "allow_external": False,
        })
        assert result.startswith("Error")

    @pytest.mark.asyncio
    async def test_dom_invalid_url_returns_error(self):
        result = await browser_get_dom.ainvoke({
            "url": "http://localhost:1",
            "allow_external": False,
        })
        assert result.startswith("Error")

    @pytest.mark.asyncio
    async def test_network_errors_invalid_url_returns_error(self):
        result = await browser_get_network_errors.ainvoke({
            "url": "http://localhost:1",
            "allow_external": False,
        })
        assert result.startswith("Error")


# ---------------------------------------------------------------------------
# Live browser tests — require MS Edge + a running server
# ---------------------------------------------------------------------------

@pytest.mark.browser
class TestBrowserLive:
    """Requires MS Edge installed and a server at http://localhost:3000."""

    @pytest.mark.asyncio
    async def test_screenshot_returns_base64_png(self):
        result = await browser_screenshot.ainvoke({
            "url": "http://localhost:3000",
            "allow_external": False,
        })
        assert result.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_console_logs_returns_json_array(self):
        import json
        result = await browser_get_console_logs.ainvoke({
            "url": "http://localhost:3000",
            "wait_ms": 1000,
            "allow_external": False,
        })
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    @pytest.mark.asyncio
    async def test_dom_returns_html(self):
        result = await browser_get_dom.ainvoke({
            "url": "http://localhost:3000",
            "allow_external": False,
        })
        assert "<" in result  # some HTML present

    @pytest.mark.asyncio
    async def test_network_errors_returns_json_array(self):
        import json
        result = await browser_get_network_errors.ainvoke({
            "url": "http://localhost:3000",
            "wait_ms": 1000,
            "allow_external": False,
        })
        parsed = json.loads(result)
        assert isinstance(parsed, list)
