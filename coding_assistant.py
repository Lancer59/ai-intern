import os
from llm_factory import get_llm
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend


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
    
    backend = FilesystemBackend(root_dir="..", virtual_mode=True)

    # 3. Define the detailed system prompt for a coding assistant
    system_prompt = f"""You are a world-class AI Software Engineer. 
You are currently working in the directory: {workspace_path} which is where all the code is present. 

Filesystem & Paths:
- ALWAYS use relative paths
- NEVER use Windows absolute paths (e.g., 'C:\\Users\\...') as they are not supported by the environment.

Capabilities:
- You have full access to the filesystem via tools like ls, read_file, write_file, edit_file.
- You can execute shell commands via the 'execute' tool.
- You should use 'write_todos' to PLAN your work before making any changes.
- You can spawn sub-agents for specialized tasks like writing documentation or specific unit tests.

Rules:
1. Always explore the project first using 'ls' or 'grep' to understand the context.
2. Be concise and professional.
3. Before executing potentially destructive shell commands (like deleting files or installing global packages), explain what you are doing.
4. If you make changes, verify them (e.g., by running tests if possible).
"""

    # 4. Initialize the DeepAgent
    # The deepagents library automatically injects filesystem and planning tools when a backend is provided.
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        # tools=[], # Add custom tools here if needed
    )

    return agent
