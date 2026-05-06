"""Tests for dashboard/db.py — telemetry and config persistence."""
import json
import os
import pytest
import tempfile

import aiosqlite


# Patch DB_PATH to a temp file for every test
@pytest.fixture(autouse=True)
def patch_db_path(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_dashboard.db")
    monkeypatch.setattr("dashboard.db.DB_PATH", db_file)
    # Also patch agent_data dir creation to use tmp
    monkeypatch.setattr("os.makedirs", lambda *a, **kw: None)
    return db_file


@pytest.fixture(autouse=True)
async def setup_db():
    from dashboard.db import init_db
    await init_db()


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    @pytest.mark.asyncio
    async def test_creates_all_tables(self):
        from dashboard.db import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cur:
                tables = {row[0] for row in await cur.fetchall()}
        assert {"llm_calls", "tool_invocations", "loc_events", "agent_config"}.issubset(tables)


# ---------------------------------------------------------------------------
# get_config / save_config
# ---------------------------------------------------------------------------

class TestConfig:
    @pytest.mark.asyncio
    async def test_get_config_returns_defaults_on_empty_db(self):
        from dashboard.db import get_config, DEFAULT_ITERATION_LIMIT
        config = await get_config()
        assert config["iteration_limit"] == DEFAULT_ITERATION_LIMIT
        assert isinstance(config["enabled_tools"], list)
        assert isinstance(config["approval_tools"], list)

    @pytest.mark.asyncio
    async def test_save_and_reload_config(self):
        from dashboard.db import get_config, save_config
        original = await get_config()
        original["iteration_limit"] = 99
        original["enabled_tools"] = ["think", "git_status"]
        await save_config(original)

        reloaded = await get_config()
        assert reloaded["iteration_limit"] == 99
        assert "think" in reloaded["enabled_tools"]

    @pytest.mark.asyncio
    async def test_save_config_overwrites_previous(self):
        from dashboard.db import get_config, save_config
        cfg = await get_config()
        cfg["iteration_limit"] = 10
        await save_config(cfg)
        cfg["iteration_limit"] = 20
        await save_config(cfg)

        reloaded = await get_config()
        assert reloaded["iteration_limit"] == 20


# ---------------------------------------------------------------------------
# record_llm_call
# ---------------------------------------------------------------------------

class TestRecordLlmCall:
    @pytest.mark.asyncio
    async def test_inserts_row(self):
        from dashboard.db import record_llm_call, DB_PATH
        await record_llm_call("thread-1", "gpt-4o", 100, 50, 150)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM llm_calls") as cur:
                rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0][3] == "gpt-4o"  # model column

    @pytest.mark.asyncio
    async def test_handles_none_tokens(self):
        from dashboard.db import record_llm_call, DB_PATH
        await record_llm_call("thread-2", "gpt-4o", None, None, None)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT prompt_tokens FROM llm_calls WHERE thread_id='thread-2'") as cur:
                row = await cur.fetchone()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# record_tool_invocation_start / end
# ---------------------------------------------------------------------------

class TestRecordToolInvocation:
    @pytest.mark.asyncio
    async def test_start_returns_id(self):
        from dashboard.db import record_tool_invocation_start
        inv_id = await record_tool_invocation_start("thread-1", "git_status")
        assert isinstance(inv_id, int)
        assert inv_id > 0

    @pytest.mark.asyncio
    async def test_end_updates_row(self):
        from dashboard.db import record_tool_invocation_start, record_tool_invocation_end, DB_PATH
        inv_id = await record_tool_invocation_start("thread-1", "git_diff")
        await record_tool_invocation_end(inv_id, 123.4, "success")

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT duration_ms, status FROM tool_invocations WHERE id=?", (inv_id,)
            ) as cur:
                row = await cur.fetchone()
        assert row[0] == pytest.approx(123.4)
        assert row[1] == "success"

    @pytest.mark.asyncio
    async def test_failure_status_recorded(self):
        from dashboard.db import record_tool_invocation_start, record_tool_invocation_end, DB_PATH
        inv_id = await record_tool_invocation_start("thread-1", "git_push")
        await record_tool_invocation_end(inv_id, 50.0, "failure")

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT status FROM tool_invocations WHERE id=?", (inv_id,)
            ) as cur:
                row = await cur.fetchone()
        assert row[0] == "failure"


# ---------------------------------------------------------------------------
# record_loc_event
# ---------------------------------------------------------------------------

class TestRecordLocEvent:
    @pytest.mark.asyncio
    async def test_inserts_positive_delta(self):
        from dashboard.db import record_loc_event, DB_PATH
        await record_loc_event("thread-1", 42)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT line_count FROM loc_events") as cur:
                row = await cur.fetchone()
        assert row[0] == 42

    @pytest.mark.asyncio
    async def test_inserts_negative_delta(self):
        from dashboard.db import record_loc_event, DB_PATH
        await record_loc_event("thread-1", -5)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT line_count FROM loc_events") as cur:
                row = await cur.fetchone()
        assert row[0] == -5
