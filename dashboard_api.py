"""
Dashboard FastAPI backend.
Provides Settings and Observability API endpoints, static file serving,
and a data export endpoint.
"""

import json
import datetime
from typing import Optional

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from dashboard_db import DB_PATH, DEFAULT_SYSTEM_PROMPT, get_config, save_config

# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

dashboard_app = FastAPI(title="Dashboard")

# Mount static files — check_dir=False so startup doesn't fail if dir is absent
try:
    dashboard_app.mount(
        "/dashboard/static",
        StaticFiles(directory="dashboard/static", html=True),
        name="dashboard_static",
    )
except Exception:
    pass  # directory doesn't exist yet; frontend not built


# ---------------------------------------------------------------------------
# HTML / redirect routes
# ---------------------------------------------------------------------------

@dashboard_app.get("/dashboard/", include_in_schema=False)
async def dashboard_redirect():
    return RedirectResponse(url="/dashboard")


@dashboard_app.get("/dashboard", include_in_schema=False)
async def dashboard_index():
    return FileResponse("dashboard/static/index.html")


# ---------------------------------------------------------------------------
# Helper — default date range (last 30 days)
# ---------------------------------------------------------------------------

def _default_dates(start: Optional[str], end: Optional[str]):
    today = datetime.date.today()
    if end is None:
        end = today.isoformat()
    if start is None:
        start = (today - datetime.timedelta(days=30)).isoformat()
    return start, end


# ---------------------------------------------------------------------------
# Task 6.2 — Settings API
# ---------------------------------------------------------------------------

@dashboard_app.get("/dashboard/api/config")
async def api_get_config():
    return await get_config()


@dashboard_app.put("/dashboard/api/config")
async def api_put_config(body: dict):
    # Validate iteration_limit
    iteration_limit = body.get("iteration_limit")
    if not isinstance(iteration_limit, int) or not (1 <= iteration_limit <= 500):
        raise HTTPException(
            status_code=422,
            detail="iteration_limit must be an integer between 1 and 500 (inclusive).",
        )

    # Validate system_prompt
    system_prompt = body.get("system_prompt")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise HTTPException(
            status_code=422,
            detail="system_prompt must be a non-empty string.",
        )

    # Validate enabled_tools
    enabled_tools = body.get("enabled_tools")
    if not isinstance(enabled_tools, list) or len(enabled_tools) < 1:
        raise HTTPException(
            status_code=422,
            detail="enabled_tools must be a list with at least 1 item.",
        )

    # Merge with existing config so read-only fields (llm_provider, model_name) are preserved
    existing = await get_config()
    existing.update(body)
    await save_config(existing)
    return {"status": "ok"}


@dashboard_app.post("/dashboard/api/config/reset-prompt")
async def api_reset_prompt():
    config = await get_config()
    config["system_prompt"] = DEFAULT_SYSTEM_PROMPT
    await save_config(config)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Task 6.3 — Observability API
# ---------------------------------------------------------------------------

@dashboard_app.get("/dashboard/api/telemetry/summary")
async def api_telemetry_summary(start: Optional[str] = None, end: Optional[str] = None):
    start, end = _default_dates(start, end)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT
                COALESCE(SUM(prompt_tokens), 0),
                COALESCE(SUM(completion_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COUNT(*)
            FROM llm_calls
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            """,
            (start, end),
        ) as cur:
            row = await cur.fetchone()
        prompt_tokens, completion_tokens, total_tokens, llm_call_count = row

        async with db.execute(
            """
            SELECT COALESCE(SUM(line_count), 0)
            FROM loc_events
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            """,
            (start, end),
        ) as cur:
            loc_row = await cur.fetchone()
        total_loc = loc_row[0]

    return {
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "llm_call_count": llm_call_count,
        "total_loc": total_loc,
    }


@dashboard_app.get("/dashboard/api/telemetry/tokens-over-time")
async def api_tokens_over_time(start: Optional[str] = None, end: Optional[str] = None):
    start, end = _default_dates(start, end)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT
                substr(timestamp, 1, 10) AS date,
                COALESCE(SUM(prompt_tokens), 0),
                COALESCE(SUM(completion_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COUNT(*) AS call_count
            FROM llm_calls
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (start, end),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {
            "date": r[0],
            "prompt_tokens": r[1],
            "completion_tokens": r[2],
            "total_tokens": r[3],
            "call_count": r[4],
        }
        for r in rows
    ]


@dashboard_app.get("/dashboard/api/telemetry/models")
async def api_telemetry_models(start: Optional[str] = None, end: Optional[str] = None):
    start, end = _default_dates(start, end)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT
                model,
                COUNT(*) AS call_count,
                COALESCE(SUM(prompt_tokens), 0),
                COALESCE(SUM(completion_tokens), 0),
                COALESCE(SUM(total_tokens), 0)
            FROM llm_calls
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY model
            ORDER BY call_count DESC
            """,
            (start, end),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {
            "model": r[0],
            "call_count": r[1],
            "prompt_tokens": r[2],
            "completion_tokens": r[3],
            "total_tokens": r[4],
        }
        for r in rows
    ]


@dashboard_app.get("/dashboard/api/telemetry/tools")
async def api_telemetry_tools(start: Optional[str] = None, end: Optional[str] = None):
    start, end = _default_dates(start, end)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT
                tool_name,
                COUNT(*) AS invocation_count,
                AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) AS avg_duration_ms,
                CAST(SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) AS REAL)
                    / COUNT(*) * 100 AS failure_rate
            FROM tool_invocations
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY tool_name
            ORDER BY invocation_count DESC
            """,
            (start, end),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {
            "tool_name": r[0],
            "invocation_count": r[1],
            "avg_duration_ms": r[2] if r[2] is not None else 0.0,
            "failure_rate": r[3] if r[3] is not None else 0.0,
        }
        for r in rows
    ]


@dashboard_app.get("/dashboard/api/telemetry/loc-over-time")
async def api_loc_over_time(start: Optional[str] = None, end: Optional[str] = None):
    start, end = _default_dates(start, end)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT
                substr(timestamp, 1, 10) AS date,
                COALESCE(SUM(line_count), 0) AS line_count
            FROM loc_events
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (start, end),
        ) as cur:
            rows = await cur.fetchall()

    return [{"date": r[0], "line_count": r[1]} for r in rows]


@dashboard_app.get("/dashboard/api/telemetry/sessions")
async def api_telemetry_sessions(start: Optional[str] = None, end: Optional[str] = None):
    start, end = _default_dates(start, end)
    async with aiosqlite.connect(DB_PATH) as db:
        # Sessions from llm_calls
        async with db.execute(
            """
            SELECT thread_id, MAX(timestamp) AS last_active
            FROM llm_calls
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY thread_id
            """,
            (start, end),
        ) as cur:
            llm_sessions = {r[0]: r[1] for r in await cur.fetchall()}

        # Sessions from tool_invocations (merge if not already present)
        async with db.execute(
            """
            SELECT thread_id, MAX(timestamp) AS last_active
            FROM tool_invocations
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY thread_id
            """,
            (start, end),
        ) as cur:
            for r in await cur.fetchall():
                tid, ts = r[0], r[1]
                if tid not in llm_sessions or ts > llm_sessions[tid]:
                    llm_sessions[tid] = ts

    sessions = sorted(
        [{"thread_id": tid, "last_active": ts} for tid, ts in llm_sessions.items()],
        key=lambda x: x["last_active"],
        reverse=True,
    )
    return sessions


@dashboard_app.get("/dashboard/api/telemetry/sessions/{thread_id}")
async def api_session_detail(thread_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, thread_id, timestamp, model, prompt_tokens, completion_tokens, total_tokens
            FROM llm_calls
            WHERE thread_id = ?
            ORDER BY timestamp
            """,
            (thread_id,),
        ) as cur:
            llm_calls = [dict(r) for r in await cur.fetchall()]

        async with db.execute(
            """
            SELECT id, thread_id, tool_name, timestamp, duration_ms, status
            FROM tool_invocations
            WHERE thread_id = ?
            ORDER BY timestamp
            """,
            (thread_id,),
        ) as cur:
            tool_invocations = [dict(r) for r in await cur.fetchall()]

        async with db.execute(
            """
            SELECT COALESCE(SUM(line_count), 0)
            FROM loc_events
            WHERE thread_id = ?
            """,
            (thread_id,),
        ) as cur:
            loc_row = await cur.fetchone()
        total_loc = loc_row[0]

    total_tokens = sum(r.get("total_tokens") or 0 for r in llm_calls)

    return {
        "llm_calls": llm_calls,
        "tool_invocations": tool_invocations,
        "total_tokens": total_tokens,
        "total_loc": total_loc,
    }


# ---------------------------------------------------------------------------
# Task 6.4 — Export endpoint
# ---------------------------------------------------------------------------

@dashboard_app.get("/dashboard/api/export")
async def api_export():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM llm_calls ORDER BY timestamp") as cur:
            llm_calls = [dict(r) for r in await cur.fetchall()]

        async with db.execute("SELECT * FROM tool_invocations ORDER BY timestamp") as cur:
            tool_invocations = [dict(r) for r in await cur.fetchall()]

        async with db.execute("SELECT * FROM loc_events ORDER BY timestamp") as cur:
            loc_events = [dict(r) for r in await cur.fetchall()]

        async with db.execute("SELECT * FROM agent_config") as cur:
            agent_config_rows = [dict(r) for r in await cur.fetchall()]

    payload = json.dumps(
        {
            "llm_calls": llm_calls,
            "tool_invocations": tool_invocations,
            "loc_events": loc_events,
            "agent_config": agent_config_rows,
        },
        indent=2,
        default=str,
    )

    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="dashboard_export.json"'},
    )
