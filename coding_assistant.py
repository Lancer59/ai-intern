import os
from llm_factory import get_llm
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, CompositeBackend, StoreBackend
from tools import think
from mcp_client import get_mcp_tools
import logging

logger = logging.getLogger("coding_assistant")


async def create_coding_assistant(workspace_path: str, checkpointer, store, user_id: str = "default"):
    """
    Creates a DeepAgent configured as an AI coding assistant for a specific workspace.
    Accepts an external checkpointer and store for persistence.
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

    system_prompt = f"""You are a world-class AI Software Engineer.

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
  * On Windows, a leading slash '/' refers to the drive root (C:\), NOT your project root.
- You should use 'write_todos' to PLAN your work before making any changes.
- You can spawn sub-agents for specialized tasks like writing documentation or specific unit tests.

Long-term Memory:
- You have persistent memory across sessions stored at /memories/.
- At the START of every conversation, read /memories/context.md if it exists to recall project context.
- When the user shares important project info (stack, preferences, conventions), save it to /memories/context.md.
- Use /memories/ for anything worth remembering across sessions.

Before responding to any user question that requires personal context (e.g., name, preferences, prior interactions), always check your persistent memory files (e.g., /memories/context.md) for relevant information. Only respond with "I don't know," "You haven't told me," or similar phrases after confirming that the requested information is not present in your memory files.

For any langchain, langgraph related code:
https://github.com/langchain-ai/langgraph
https://github.com/langchain-ai/langchain
Use deepwiki tools with this

For anything related to Microsoft:
Use the microsoft-docs tools

Rules:
1. Always explore the project first using 'ls' or 'grep' to understand the context.
2. Be concise and professional.
3. Before executing potentially destructive shell commands, explain what you are doing.
4. If you make changes, verify them (e.g., by running tests if possible).
5. ALWAYS use 'edit_file' to modify existing files. NEVER use 'write_file' on a file that already exists.
"""

    logger.info("Fetching MCP tools...")
    mcp_tools = await get_mcp_tools()
    logger.info(f"MCP tools loaded: {[t.name for t in mcp_tools]}")

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
        system_prompt=system_prompt,
        backend=make_backend,
        checkpointer=checkpointer,
        store=store,
        tools=mcp_tools + [think],
        interrupt_on={"execute": {"allowed_decisions": ["approve", "reject"]}},
    )

    return agent
