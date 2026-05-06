import os
import pathlib
from core.llm_factory import get_llm
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, CompositeBackend, StoreBackend
from tools.custom_tools import think, read_package_source
from tools.browser_tools import (
    browser_screenshot,
    browser_get_console_logs,
    browser_get_dom,
    browser_click_and_screenshot,
    browser_get_network_errors,
)
from tools.git_tools import (
    git_clone,
    git_status,
    git_diff,
    git_log,
    git_blame,
    git_commit,
    git_create_branch,
    git_checkout,
    git_push,
    git_pull,
    git_stash,
    git_generate_commit_message,
)
# For now vector DB functionality is commented, will be used once required.
# from tools.vector_search import semantic_code_search, rebuild_code_index
from core.mcp_client import get_mcp_tools
from langchain.agents.middleware import (
    SummarizationMiddleware,
    PIIMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
import re
import logging

logger = logging.getLogger("coding_assistant")

# ---------------------------------------------------------------------------
# Custom PII detectors for secrets commonly found in codebases
# ---------------------------------------------------------------------------

# Matches: password = "...", PASSWORD="...", passwd: '...', etc.
_PASSWORD_RE = re.compile(
    r'(?i)(password|passwd|pwd|secret|client_secret|db_password|db_pass)\s*[:=]\s*["\']([^"\']{4,})["\']'
)

def _detect_passwords(content: str) -> list[dict]:
    return [
        {"text": m.group(2), "start": m.start(2), "end": m.end(2)}
        for m in _PASSWORD_RE.finditer(content)
        if m.group(2).lower() not in ("", "your_password_here", "changeme", "xxxx")
    ]

# Matches common secret key patterns: sk-..., ghp_..., xoxb-..., AKIA..., etc.
_SECRET_KEY_RE = re.compile(
    r'\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|'
    r'xoxb-[0-9A-Za-z\-]{50,}|AKIA[0-9A-Z]{16}|'
    r'[A-Za-z0-9+/]{40,}={0,2})\b'  # generic long base64-ish tokens
)

def _detect_secret_keys(content: str) -> list[dict]:
    return [
        {"text": m.group(0), "start": m.start(), "end": m.end()}
        for m in _SECRET_KEY_RE.finditer(content)
    ]

# Directories to skip when building the repo map
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".tox", "*.egg-info",
}
# File extensions to include in the repo map
_MAP_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".cs",
    ".cpp", ".c", ".h", ".rb", ".php", ".swift", ".kt", ".scala",
    ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml",
    ".md", ".sh", ".env.example", ".dockerfile", "dockerfile",
}
_MAX_MAP_FILES = 300  # cap to avoid huge prompts


def _build_repo_map(workspace_path: str, repo_folder: str) -> str:
    """Walk the workspace and return a compact tree of source files."""
    lines = [f"## Repo Map: {repo_folder}/"]
    count = 0
    try:
        for root, dirs, files in os.walk(workspace_path):
            # Prune skip dirs in-place
            dirs[:] = sorted(
                d for d in dirs
                if d not in _SKIP_DIRS and not d.startswith(".")
            )
            rel_root = os.path.relpath(root, workspace_path)
            depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
            indent = "  " * depth
            folder_name = os.path.basename(root) if rel_root != "." else repo_folder
            if rel_root != ".":
                lines.append(f"{indent}📁 {folder_name}/")
            for fname in sorted(files):
                ext = pathlib.Path(fname).suffix.lower()
                if ext in _MAP_EXTENSIONS or fname.lower() in {"makefile", "dockerfile", ".ai-intern-rules"}:
                    file_indent = "  " * (depth + 1)
                    lines.append(f"{file_indent}📄 {fname}")
                    count += 1
                    if count >= _MAX_MAP_FILES:
                        lines.append(f"  ... (truncated at {_MAX_MAP_FILES} files)")
                        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Repo map generation failed: {e}")
        return ""
    return "\n".join(lines)


def _read_ai_intern_rules(workspace_path: str) -> str:
    """Read .ai-intern-rules from the target repo if it exists."""
    rules_path = os.path.join(workspace_path, ".ai-intern-rules")
    if os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                logger.info(f"Loaded .ai-intern-rules from {rules_path}")
                return content
        except Exception as e:
            logger.warning(f"Could not read .ai-intern-rules: {e}")
    return ""


async def create_coding_assistant(
    workspace_path: str,
    checkpointer,
    store,
    user_id: str = "default",
    system_prompt: str = None,
    iteration_limit: int = None,
    enabled_tools: list = None,
    approval_tools: list = None,
):
    """
    Creates a DeepAgent configured as an AI coding assistant for a specific workspace.
    Accepts an external checkpointer and store for persistence.

    Optional config overrides:
    - system_prompt: custom system prompt (supports {agent_folder} and {repo_folder} placeholders)
    - iteration_limit: max agent loop iterations; stored as agent._iteration_limit
    - enabled_tools: list of tool names to allow; None means all tools
    - approval_tools: list of tool names requiring approval; None defaults to ["execute"]
    """
    if not os.path.exists(workspace_path):
        os.makedirs(workspace_path)

    llm = get_llm(provider="azure")
    # llm = get_llm(provider="openai", model_name="codex-mini-latest", use_responses_api=True)

    persistence_path = "deepagents_data"
    if not os.path.exists(persistence_path):
        os.makedirs(persistence_path)

    parent_dir = os.path.abspath(os.path.join(workspace_path, ".."))
    shell_backend = LocalShellBackend(root_dir=parent_dir, virtual_mode=True, inherit_env=True)

    agent_folder = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    repo_folder = os.path.basename(workspace_path)

    # Build repo map and read project rules
    repo_map = _build_repo_map(workspace_path, repo_folder)
    ai_intern_rules = _read_ai_intern_rules(workspace_path)

    repo_map_section = f"\n\n## Semantic Repo Map\nThis is the current file structure of the target repository:\n\n{repo_map}" if repo_map else ""
    rules_section = f"\n\n## Project-Specific Rules (.ai-intern-rules)\nThe project has defined the following rules and conventions — follow them strictly:\n\n{ai_intern_rules}" if ai_intern_rules else ""

    if system_prompt is not None:
        resolved_prompt = system_prompt.replace("{agent_folder}", agent_folder).replace("{repo_folder}", repo_folder)
        resolved_prompt += repo_map_section + rules_section
    else:
        resolved_prompt = (
            "You are a world-class AI Software Engineer working inside an agentic coding assistant.\n\n"

            "## Environment\n"
            f"- Virtual filesystem root '/' = parent directory of both this assistant and the target repo.\n"
            f"- Assistant data: '/{agent_folder}/'\n"
            f"- Target repository: '/{repo_folder}/' — THIS is where you make all changes.\n\n"

            "## Path Rules (CRITICAL on Windows)\n"
            f"- ALWAYS use relative paths: '{repo_folder}/src/main.py', NOT '/repo/src/main.py'.\n"
            "- NEVER use Windows absolute paths (C:\\Users\\...).\n"
            "- In shell commands, NEVER prefix paths with '/'. On Windows '/' resolves to the drive root.\n"
            f"  ✅ DO: pip install -r {repo_folder}/requirements.txt\n"
            f"  ❌ DON'T: pip install -r /{repo_folder}/requirements.txt\n\n"

            "## Task Planning & Todo List (MANDATORY)\n"
            "The todo list is displayed live in the UI. Users watch it update in real time. Keep it accurate.\n\n"
            "RULES — follow these without exception:\n"
            "1. Call `write_todos` at the START of every multi-step task to create the full plan.\n"
            "2. Before starting each task item, call `write_todos` to mark it `in_progress`.\n"
            "3. After completing each task item, call `write_todos` to mark it `done`.\n"
            "4. If you discover new sub-tasks mid-execution, add them immediately via `write_todos`.\n"
            "5. NEVER declare a task complete in your final message if any todo item is still `pending` or `in_progress`.\n"
            "6. For simple single-step requests (e.g. 'what does this function do?'), skip the todo list.\n\n"

            "## File Operations\n"
            "- ALWAYS use `edit_file` to modify existing files. NEVER use `write_file` on an existing file.\n"
            "- Use `grep_search` to find files and line numbers before reading or editing.\n"
            "- Use `semantic_code_search` when you need to find code by concept rather than exact keyword.\n"
            "- Use `read_package_source` to inspect installed library internals before using them.\n\n"

            "## Shell Execution\n"
            "- Use `execute` for shell commands. Always explain what a destructive command will do before running it.\n"
            "- After running tests or linters, capture the output and fix any errors before declaring done.\n\n"

            "## Long-term Memory\n"
            "- At the START of every conversation, read /memories/context.md if it exists.\n"
            "- Save important project info (stack, conventions, preferences) to /memories/context.md.\n"
            "- Never say 'I don't know' about project context without first checking /memories/context.md.\n\n"

            "## External Knowledge\n"
            "- For LangChain/LangGraph questions: use deepwiki tools with https://github.com/langchain-ai/langgraph\n"
            "- For Microsoft/Azure questions: use the microsoft-docs MCP tools.\n\n"

            "## Code Quality Rules\n"
            "1. Explore the project structure first — use `ls`, `grep_search`, or `semantic_code_search`.\n"
            "2. Match the existing code style, naming conventions, and library choices.\n"
            "3. Verify changes by running tests or the linter when possible.\n"
            "4. Be concise. Don't add unnecessary abstractions or boilerplate.\n"
            "5. Before spawning sub-agents, confirm the task genuinely benefits from isolation.\n"
        ) + repo_map_section + rules_section

    logger.info("Fetching MCP tools...")
    mcp_tools = await get_mcp_tools()
    logger.info(f"MCP tools loaded: {[t.name for t in mcp_tools]}")

    # Core local tools — always included regardless of enabled_tools filter
    core_tools = [
        think,
        read_package_source,
        # Below vector DB tools are commented for now as Embedding model has not been configured.
        # semantic_code_search,
        # rebuild_code_index,
        browser_screenshot,
        browser_get_console_logs,
        browser_get_dom,
        browser_click_and_screenshot,
        browser_get_network_errors,
        git_clone,
        git_status,
        git_diff,
        git_log,
        git_blame,
        git_commit,
        git_create_branch,
        git_checkout,
        git_push,
        git_pull,
        git_stash,
        git_generate_commit_message,
    ]
    all_tools = mcp_tools + core_tools

    # Always persist the full known tool list so the dashboard can show all tools,
    # even those the user has disabled.
    try:
        from dashboard.db import get_config, save_config
        cfg = await get_config()
        cfg["all_known_tools"] = [t.name for t in all_tools]
        await save_config(cfg)
    except Exception as e:
        logger.warning(f"Could not persist all_known_tools: {e}")

    if enabled_tools is not None:
        enabled_set = set(enabled_tools)
        all_tool_names = {t.name for t in all_tools}

        # Add genuinely new tools (ones that didn't exist when config was last saved)
        # as enabled by default, so they appear in the dashboard.
        new_tools = [n for n in all_tool_names if n not in enabled_set]
        if new_tools:
            logger.info(f"New tools discovered, adding to config as enabled: {new_tools}")
            enabled_set.update(new_tools)
            try:
                from dashboard.db import get_config, save_config
                cfg = await get_config()
                cfg["enabled_tools"] = list(enabled_set)
                cfg["all_known_tools"] = list(all_tool_names)
                await save_config(cfg)
            except Exception as e:
                logger.warning(f"Could not sync new tool names to config: {e}")

        def _tool_allowed(t):
            return t.name in enabled_set

        filtered = [t for t in all_tools if _tool_allowed(t)]
        logger.info(f"Tools active ({len(filtered)}): {[t.name for t in filtered]}")
        all_tools = filtered

    if approval_tools is not None:
        interrupt_on = {name: {"allowed_decisions": ["approve", "reject"]} for name in approval_tools}
    else:
        interrupt_on = {"execute": {"allowed_decisions": ["approve", "reject"]}}

    def make_backend(runtime):
        return CompositeBackend(
            default=shell_backend,  # handles files on disk + shell execution
            routes={
                "/memories/": StoreBackend(
                    runtime,
                    namespace=lambda ctx, uid=user_id: (uid,),
                )
            }
        )

    agent = create_deep_agent(
        model=llm,
        system_prompt=resolved_prompt,
        backend=make_backend,
        checkpointer=checkpointer,
        store=store,
        tools=all_tools,
        interrupt_on=interrupt_on,
        middleware=[
            # Auto-summarise old messages when the conversation approaches the
            # model's context limit — keeps long coding sessions from failing.
            # TOKEN LIMIT: set SUMMARIZATION_TOKEN_TRIGGER in .env to match your
            # model's context window (default 100000 for gpt-4o / 128k models).
            # Use absolute token counts — fractional limits require model profile
            # metadata that Azure/custom deployments don't always expose.
            SummarizationMiddleware(
                model=llm,
                trigger=("tokens", int(os.getenv("SUMMARIZATION_TOKEN_TRIGGER", "100000"))),
                keep=("messages", int(os.getenv("SUMMARIZATION_KEEP_MESSAGES", "30"))),
            ),
            # Redact common PII patterns before they reach the LLM or logs.
            PIIMiddleware("email", strategy="redact", apply_to_input=True),
            PIIMiddleware("credit_card", strategy="mask", apply_to_input=True),
            # Redact passwords and client secrets found in codebase files.
            # Catches: password="...", client_secret='...', passwd: "..." etc.
            PIIMiddleware("password", detector=_detect_passwords, strategy="redact", apply_to_input=True),
            # Catches: OpenAI keys (sk-...), GitHub tokens (ghp_...), AWS keys (AKIA...), etc.
            PIIMiddleware("secret_key", detector=_detect_secret_keys, strategy="redact", apply_to_input=True),
            # Retry transient model API failures (rate limits, 503s) with backoff.
            ModelRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            # Retry transient tool failures (network blips in browser/git/MCP tools).
            ToolRetryMiddleware(max_retries=2, backoff_factor=1.5, initial_delay=0.5),
        ],
    )

    # Store iteration_limit so assistant_ui.py can use it as recursion_limit
    agent._iteration_limit = iteration_limit if iteration_limit is not None else 50

    return agent
