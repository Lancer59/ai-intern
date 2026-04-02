import os
from llm_factory import get_llm
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, CompositeBackend, StoreBackend
from tools import think
from mcp_client import get_mcp_tools
import logging

logger = logging.getLogger("coding_assistant")


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

    if system_prompt is not None:
        # Apply workspace-specific substitutions to the custom prompt
        resolved_prompt = system_prompt.replace("{agent_folder}", agent_folder).replace("{repo_folder}", repo_folder)
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
            "Rules:\n"
            "1. Always explore the project first using 'ls' or 'grep' to understand the context.\n"
            "2. Be concise and professional.\n"
            "3. Before executing potentially destructive shell commands, explain what you are doing.\n"
            "4. If you make changes, verify them (e.g., by running tests if possible).\n"
            "5. ALWAYS use 'edit_file' to modify existing files. NEVER use 'write_file' on a file that already exists.\n"
        )

    logger.info("Fetching MCP tools...")
    mcp_tools = await get_mcp_tools()
    logger.info(f"MCP tools loaded: {[t.name for t in mcp_tools]}")

    all_tools = mcp_tools + [think]
    if enabled_tools is not None:
        enabled_set = set(enabled_tools)
        # Match exact tool names OR group prefixes (e.g. "tavily" matches "tavily_search")
        def _tool_allowed(t):
            return t.name in enabled_set or any(t.name.startswith(prefix) for prefix in enabled_set)
        filtered = [t for t in all_tools if _tool_allowed(t)]
        # If filtering wiped out almost everything (only think left or empty),
        # it likely means the DB has stale group names — fall back to all tools
        # and update the config with real names so next session is correct.
        if len(filtered) <= 1 and len(all_tools) > 1:
            logger.warning("Tool filter produced too few results — stored names may be stale group names. Using all tools and updating config.")
            filtered = all_tools
            try:
                from dashboard_db import get_config, save_config
                cfg = await get_config()
                cfg["enabled_tools"] = [t.name for t in all_tools]
                await save_config(cfg)
                logger.info(f"Updated enabled_tools in config to actual tool names: {cfg['enabled_tools']}")
            except Exception as e:
                logger.warning(f"Could not update tool names in config: {e}")
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
