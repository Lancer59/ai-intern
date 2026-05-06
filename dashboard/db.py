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
                model_name      TEXT,
                all_known_tools TEXT
            )
        """)

        await db.commit()


# Default system prompt (generic version without workspace-specific f-string variables)
DEFAULT_SYSTEM_PROMPT = """You are a world-class AI Software Engineer working inside an agentic coding assistant.

## Environment
- Virtual filesystem root '/' = parent directory of both this assistant and the target repo.
- Assistant data: '/{agent_folder}/'
- Target repository: '/{repo_folder}/' — THIS is where you make all changes.

## Path Rules (CRITICAL on Windows)
- ALWAYS use relative paths: '{repo_folder}/src/main.py', NOT '/repo/src/main.py'.
- NEVER use Windows absolute paths (C:\\Users\\...).
- In shell commands, NEVER prefix paths with '/'. On Windows '/' resolves to the drive root.
  ✅ DO: pip install -r {repo_folder}/requirements.txt
  ❌ DON'T: pip install -r /{repo_folder}/requirements.txt

## Task Planning & Todo List (MANDATORY)
The todo list is displayed live in the UI. Users watch it update in real time. Keep it accurate.

RULES — follow these without exception:
1. Call `write_todos` at the START of every multi-step task to create the full plan.
2. Before starting each task item, call `write_todos` to mark it `in_progress`.
3. After completing each task item, call `write_todos` to mark it `done`.
4. If you discover new sub-tasks mid-execution, add them immediately via `write_todos`.
5. NEVER declare a task complete in your final message if any todo item is still `pending` or `in_progress`.
6. For simple single-step requests (e.g. 'what does this function do?'), skip the todo list.

## File Operations
- ALWAYS use `edit_file` to modify existing files. NEVER use `write_file` on an existing file.
- Use `grep_search` to find files and line numbers before reading or editing.
- Use `semantic_code_search` when you need to find code by concept rather than exact keyword.
- Use `read_package_source` to inspect installed library internals before using them.

## Shell Execution
- Use `execute` for shell commands. Always explain what a destructive command will do before running it.
- After running tests or linters, capture the output and fix any errors before declaring done.

## Long-term Memory
- At the START of every conversation, read /memories/context.md if it exists.
- Save important project info (stack, conventions, preferences) to /memories/context.md.
- Never say 'I don't know' about project context without first checking /memories/context.md.

## External Knowledge
- For LangChain/LangGraph questions: use deepwiki tools with https://github.com/langchain-ai/langgraph
- For Microsoft/Azure questions: use the microsoft-docs MCP tools.

## Code Quality Rules
1. Explore the project structure first — use `ls`, `grep_search`, or `semantic_code_search`.
2. Match the existing code style, naming conventions, and library choices.
3. Verify changes by running tests or the linter when possible.
4. Be concise. Don't add unnecessary abstractions or boilerplate.
5. Before spawning sub-agents, confirm the task genuinely benefits from isolation.
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
        # Add all_known_tools column if it doesn't exist (migration for existing DBs)
        try:
            await db.execute("ALTER TABLE agent_config ADD COLUMN all_known_tools TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists

        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM agent_config WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        defaults = _build_defaults()
        await save_config(defaults)
        return defaults

    all_known_raw = row["all_known_tools"] if "all_known_tools" in row.keys() else None
    all_known = json.loads(all_known_raw) if all_known_raw else json.loads(row["enabled_tools"])

    return {
        "system_prompt": row["system_prompt"],
        "iteration_limit": row["iteration_limit"],
        "enabled_tools": json.loads(row["enabled_tools"]),
        "all_known_tools": all_known,
        "approval_tools": json.loads(row["approval_tools"]),
        "llm_provider": row["llm_provider"],
        "model_name": row["model_name"],
    }


async def save_config(config: dict) -> None:
    """
    Upserts the agent_config row (INSERT OR REPLACE with id=1).
    Serializes list fields to JSON strings before storing.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Add all_known_tools column if it doesn't exist (migration for existing DBs)
        try:
            await db.execute("ALTER TABLE agent_config ADD COLUMN all_known_tools TEXT")
            await db.commit()
        except Exception:
            pass

        all_known = config.get("all_known_tools", config.get("enabled_tools", []))

        await db.execute(
            """
            INSERT OR REPLACE INTO agent_config
                (id, system_prompt, iteration_limit, enabled_tools, approval_tools,
                 llm_provider, model_name, all_known_tools)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config["system_prompt"],
                config["iteration_limit"],
                json.dumps(config["enabled_tools"]),
                json.dumps(config["approval_tools"]),
                config["llm_provider"],
                config["model_name"],
                json.dumps(all_known),
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
