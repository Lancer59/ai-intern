import os
from llm_factory import get_llm
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langgraph.checkpoint.memory import MemorySaver

# Single shared checkpointer instance for in-memory persistence
memory_saver = MemorySaver()


def create_coding_assistant(workspace_path: str):
    """
    Creates a DeepAgent configured as an AI coding assistant for a specific workspace.
    """
    if not os.path.exists(workspace_path):
        os.makedirs(workspace_path)

    # 1. Get the LLM (using Azure as per user's latest preference)
    # Note: Using gpt-4o as gpt-4.1 might not be a standard deployment name, 
    # but we'll follow the factory's flexibility.
    llm = get_llm(provider="azure")

    # 2. Configure persistence and filesystem tools
    # We'll use a hidden .deepagents folder in the workspace for persistence
    persistence_path = "deepagents_data"
    if not os.path.exists(persistence_path):
        os.makedirs(persistence_path)
    
    # Use absolute path for root_dir to avoid Windows issues with subprocess
    parent_dir = os.path.abspath(os.path.join(workspace_path, ".."))
    backend = LocalShellBackend(root_dir=parent_dir, virtual_mode=True, inherit_env=True)

    # 3. Define the detailed system prompt for a coding assistant
    # We clarify the directory structure for the agent
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

Rules:
1. Always explore the project first using 'ls' or 'grep' to understand the context.
2. Be concise and professional.
3. Before executing potentially destructive shell commands (like deleting files or installing global packages), explain what you are doing.
4. If you make changes, verify them (e.g., by running tests if possible).
5. ALWAYS use 'edit_file' to modify existing files. NEVER use 'write_file' on a file that already exists — it will error. Use 'write_file' only for creating brand new files.
"""

    # 4. Initialize the DeepAgent
    # The deepagents library automatically injects filesystem and planning tools when a backend is provided.
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        checkpointer=memory_saver,
        # tools=[], # Add custom tools here if needed
    )

    return agent
