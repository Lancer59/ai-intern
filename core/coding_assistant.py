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
from core.mcp_client import get_mcp_tools
import logging

logger = logging.getLogger("coding_assistant")

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
            "You are a world-class AI Software Engineer.\n\n"
            "Environment Mapping:\n"
            f"- Your virtual filesystem root '/' is the parent directory of both this assistant and the target repository.\n"
            f"- Assistant logs/data: '/{agent_folder}/'\n"
            f"- Target Code Repository: '/{repo_folder}/' (This is where you should make changes!)\n\n"
            "Filesystem & Paths:\n"
            f"- ALWAYS use relative paths to access the code (e.g., '{repo_folder}/src/main.py').\n"
            "- NEVER use Windows absolute paths (e.g., 'C:\\Users\\...') as they are not supported.\n"
            "- Use 'grep' for efficient keyword searches across the project to find specific file and line numbers quickly.\n"
            "- You can execute shell commands via the 'execute' tool.\n"
            "- CRITICAL (Windows Path Handling): Your terminal 'cwd' is the virtual root '/'.\n"
            "  * NEVER use a leading slash in shell commands (e.g., NEVER do 'pip install -r /repo/reqs.txt').\n"
            f"  * ALWAYS use relative paths without a leading slash (e.g., DO 'pip install -r {repo_folder}/requirements.txt').\n"
            "  * On Windows, a leading slash '/' refers to the drive root (C:\\), NOT your project root.\n"
            "- You should use 'write_todos' to PLAN your work before making any changes.\n"
            "- You can spawn sub-agents for specialized tasks like writing documentation or specific unit tests.\n\n"
            "Long-term Memory:\n"
            "- You have persistent memory across sessions stored at /memories/.\n"
            "- At the START of every conversation, read /memories/context.md if it exists to recall project context.\n"
            "- When the user shares important project info (stack, preferences, conventions), save it to /memories/context.md.\n"
            "- Use /memories/ for anything worth remembering across sessions.\n\n"
            "Before responding to any user question that requires personal context (e.g., name, preferences, prior interactions), "
            "always check your persistent memory files (e.g., /memories/context.md) for relevant information. "
            "Only respond with \"I don't know,\" \"You haven't told me,\" or similar phrases after confirming that the requested information is not present in your memory files.\n\n"
            "For any langchain, langgraph related code:\n"
            "https://github.com/langchain-ai/langgraph\n"
            "https://github.com/langchain-ai/langchain\n"
            "Use deepwiki tools with this\n\n"
            "For anything related to Microsoft:\n"
            "Use the microsoft-docs tools\n\n"
            "Package Source Inspection:\n"
            "- Use the 'read_package_source' tool to read the source code of any installed package.\n"
            "- Example: read_package_source('langgraph.prebuilt.chat_agent_executor') to see how create_react_agent is implemented.\n"
            "- Use this BEFORE implementing anything that depends on a library's internals — don't guess, read the source.\n\n"
            "Rules:\n"
            "1. Always explore the project first using 'ls' or 'grep' to understand the context.\n"
            "2. Be concise and professional.\n"
            "3. Before executing potentially destructive shell commands, explain what you are doing.\n"
            "4. If you make changes, verify them (e.g., by running tests if possible).\n"
            "5. ALWAYS use 'edit_file' to modify existing files. NEVER use 'write_file' on a file that already exists.\n"
        ) + repo_map_section + rules_section

    logger.info("Fetching MCP tools...")
    mcp_tools = await get_mcp_tools()
    logger.info(f"MCP tools loaded: {[t.name for t in mcp_tools]}")

    # Core local tools — always included regardless of enabled_tools filter
    core_tools = [
        think,
        read_package_source,
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

    if enabled_tools is not None:
        enabled_set = set(enabled_tools)
        # Check if any new tools are missing from the stored list and add them
        all_tool_names = [t.name for t in all_tools]
        new_tools = [n for n in all_tool_names if n not in enabled_set]
        if new_tools:
            logger.info(f"New tools not in stored config, adding: {new_tools}")
            enabled_set.update(new_tools)
            try:
                from dashboard.db import get_config, save_config
                cfg = await get_config()
                # Merge: keep existing enabled state, add new tools as enabled
                cfg["enabled_tools"] = list(enabled_set)
                await save_config(cfg)
            except Exception as e:
                logger.warning(f"Could not sync new tool names to config: {e}")

        def _tool_allowed(t):
            return t.name in enabled_set or any(t.name.startswith(p) for p in enabled_set)
        filtered = [t for t in all_tools if _tool_allowed(t)]
        # Self-heal: if stale group names wiped all MCP tools, reset to all
        mcp_filtered = [t for t in filtered if t.name not in {c.name for c in core_tools}]
        if len(mcp_filtered) == 0 and len(mcp_tools) > 0:
            logger.warning("Tool filter removed all MCP tools — stored names may be stale. Resetting config.")
            filtered = all_tools
            try:
                from dashboard.db import get_config, save_config
                cfg = await get_config()
                cfg["enabled_tools"] = [t.name for t in all_tools]
                await save_config(cfg)
                logger.info(f"Reset enabled_tools in config: {cfg['enabled_tools']}")
            except Exception as e:
                logger.warning(f"Could not reset tool names in config: {e}")
        all_tools = filtered
        logger.info(f"Tools filtered to: {[t.name for t in all_tools]}")

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
    )

    # Store iteration_limit so assistant_ui.py can use it as recursion_limit
    agent._iteration_limit = iteration_limit if iteration_limit is not None else 50

    return agent
