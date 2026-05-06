"""
Dashboard database setup and async SQLite helpers.
Uses aiosqlite for async access to agent_data/dashboard.db.
"""

import datetime
import json
import logging
import os
import aiosqlite

DB_PATH = os.path.join("agent_data", "dashboard.db")


async def init_db() -> None:
    """Create agent_data/dashboard.db and all dashboard tables if they don't exist."""
    os.makedirs("agent_data", exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id        TEXT,
                timestamp        TEXT,
                model            TEXT,
                prompt_tokens    INTEGER,
                completion_tokens INTEGER,
                total_tokens     INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tool_invocations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id   TEXT,
                tool_name   TEXT,
                timestamp   TEXT,
                duration_ms REAL,
                status      TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS loc_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id  TEXT,
                timestamp  TEXT,
                line_count INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_config (
                id              INTEGER PRIMARY KEY,
                system_prompt   TEXT,
                iteration_limit INTEGER,
                enabled_tools   TEXT,
                approval_tools  TEXT,
                llm_provider    TEXT,
                model_name      TEXT
            )
        """)

        await db.commit()


# Default system prompt (generic version without workspace-specific f-string variables)
DEFAULT_SYSTEM_PROMPT = """You are a world-class AI Software Engineer.

Environment Mapping:
- Your virtual filesystem root '/' is the parent directory of both this assistant and the target repository.
- Assistant logs/data: '/{agent_folder}/'
- Target Code Repository: '/{repo_folder}/' (This is where you should make changes!)

Filesystem & Paths:
- ALWAYS use relative paths to access the code (e.g., '{repo_folder}/src/main.py').
- NEVER use Windows absolute paths (e.g., 'C:\\Users\\...') as they are not supported.
- Use 'grep' for efficient keyword searches across the project to find specific file and line numbers quickly.
- You can execute shell commands via the 'execute' tool.
- CRITICAL (Windows Path Handling): Your terminal 'cwd' is the virtual root '/'.
  * NEVER use a leading slash in shell commands (e.g., NEVER do 'pip install -r /repo/reqs.txt').
  * ALWAYS use relative paths without a leading slash (e.g., DO 'pip install -r {repo_folder}/requirements.txt').
  * On Windows, a leading slash '/' refers to the drive root (C:\\), NOT your project root.
- You should use 'write_todos' to PLAN your work before making any changes.
- You can spawn sub-agents for specialized tasks like writing documentation or specific unit tests.

Long-term Memory:
- You have persistent memory across sessions stored at /memories/.
- At the START of every conversation, read /memories/context.md if it exists to recall project context.
- When the user shares important project info (stack, preferences, conventions), save it to /memories/context.md.
- Use /memories/ for anything worth remembering across sessions.

Before responding to any user question that requires personal context (e.g., name, preferences, prior interactions), always check your persistent memory files (e.g., /memories/context.md) for relevant information. Only respond with "I don't know," "You haven't told me," or similar phrases after confirming that the requested information is not present in your memory files.

Rules:
1. Always explore the project first using 'ls' or 'grep' to understand the context.
2. Be concise and professional.
3. Before executing potentially destructive shell commands, explain what you are doing.
4. If you make changes, verify them (e.g., by running tests if possible).
5. ALWAYS use 'edit_file' to modify existing files. NEVER use 'write_file' on a file that already exists.
"""

# Default MCP tool names (from MCP_CONFIGS servers) plus "think"
DEFAULT_ENABLED_TOOLS = [
    "microsoft_docs",
    "tavily",
    "deepwiki",
    "think",
]

DEFAULT_APPROVAL_TOOLS = ["execute"]

DEFAULT_ITERATION_LIMIT = 50
DEFAULT_LLM_PROVIDER = "azure"
DEFAULT_MODEL_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")


def _build_defaults() -> dict:
    return {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "iteration_limit": DEFAULT_ITERATION_LIMIT,
        "enabled_tools": DEFAULT_ENABLED_TOOLS,
        "approval_tools": DEFAULT_APPROVAL_TOOLS,
        "llm_provider": DEFAULT_LLM_PROVIDER,
        "model_name": DEFAULT_MODEL_NAME,
    }


async def get_config() -> dict:
    """
    Reads the single agent_config row (id=1).
    If no row exists, seeds defaults and returns them.
    Returns a dict with enabled_tools and approval_tools already parsed as Python lists.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM agent_config WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        defaults = _build_defaults()
        await save_config(defaults)
        return defaults

    return {
        "system_prompt": row["system_prompt"],
        "iteration_limit": row["iteration_limit"],
        "enabled_tools": json.loads(row["enabled_tools"]),
        "approval_tools": json.loads(row["approval_tools"]),
        "llm_provider": row["llm_provider"],
        "model_name": row["model_name"],
    }


async def save_config(config: dict) -> None:
    """
    Upserts the agent_config row (INSERT OR REPLACE with id=1).
    Serializes enabled_tools and approval_tools lists to JSON strings before storing.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_config
                (id, system_prompt, iteration_limit, enabled_tools, approval_tools, llm_provider, model_name)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
            (
                config["system_prompt"],
                config["iteration_limit"],
                json.dumps(config["enabled_tools"]),
                json.dumps(config["approval_tools"]),
                config["llm_provider"],
                config["model_name"],
            ),
        )
        await db.commit()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 3.1 — LLM call telemetry (Requirements 7.1, 7.2, 7.3)
# ---------------------------------------------------------------------------

async def record_llm_call(
    thread_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """Insert a row into llm_calls for a completed LLM request."""
    if prompt_tokens is None or completion_tokens is None or total_tokens is None:
        logger.warning(
            "record_llm_call: missing token metadata for thread_id=%s model=%s; defaulting to 0",
            thread_id,
            model,
        )
        prompt_tokens = prompt_tokens or 0
        completion_tokens = completion_tokens or 0
        total_tokens = total_tokens or 0

    timestamp = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO llm_calls (thread_id, timestamp, model, prompt_tokens, completion_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thread_id, timestamp, model, prompt_tokens, completion_tokens, total_tokens),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Task 3.2 — Tool invocation telemetry (Requirements 8.1, 8.2)
# ---------------------------------------------------------------------------

async def record_tool_invocation_start(thread_id: str, tool_name: str) -> int:
    """Insert a pending tool_invocations row and return its new id."""
    timestamp = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO tool_invocations (thread_id, tool_name, timestamp, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (thread_id, tool_name, timestamp),
        )
        await db.commit()
        return cursor.lastrowid


async def record_tool_invocation_end(
    invocation_id: int, duration_ms: float, status: str
) -> None:
    """Update an existing tool_invocations row with duration and final status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE tool_invocations
            SET duration_ms = ?, status = ?
            WHERE id = ?
            """,
            (duration_ms, status, invocation_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Task 3.3 — Lines-of-code event telemetry (Requirements 9.1, 9.2, 9.3)
# ---------------------------------------------------------------------------

async def record_loc_event(thread_id: str, line_count: int) -> None:
    """Insert a row into loc_events.

    line_count is the total line count for write_file operations, or the net
    delta (lines added minus lines removed) for edit_file operations.
    """
    timestamp = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO loc_events (thread_id, timestamp, line_count)
            VALUES (?, ?, ?)
            """,
            (thread_id, timestamp, line_count),
        )
        await db.commit()
