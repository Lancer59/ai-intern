import os
from typing import List, Dict, Any, Optional

# Import the LLM factory
from llm_factory import get_llm

# IMPORTANT: Ensure deepagents is installed: pip install deepagents
# from deepagents import create_deep_agent # Assuming this is the correct import path

def initialize_deep_agent():
    """
    Initializes a DeepAgent using the deepagents library with all available parameters.
    Configured with FilesystemBackend to persist tasks to the 'agent_data' folder.
    """
    from deepagents import create_deep_agent, FilesystemBackend
    
    # 1. Get the LLM from our factory
    # User updated this to Azure (consistent with their last edit)
    llm = get_llm(provider="azure", model_name="gpt-4.1")

    # 2. Define some basic tools (required)
    def my_tool(query: str) -> str:
        """A simple placeholder tool."""
        return f"Tool result for: {query}"

    tools = [my_tool]

    # 3. Initialize the FilesystemBackend for persistence
    # This will save todo lists and other tasks to the 'agent_data' folder
    backend = FilesystemBackend(root_dir="./agent_data")

    # 4. Initialize the DeepAgent
    agent = create_deep_agent(
        tools=tools,
        system_prompt="You are a helpful assistant capable of multi-step planning and file system operations.", # Using system_prompt as per user edit
        model=llm,
        backends=backend,                 # Set the backend for persistence
        # subagents=[],                   
        # middleware=[],                  
        # tool_configs={},                
        # checkpointer=None,              
        # interrupt_on=[],                
        # memory=None,                    
        # skills=[],                      
    )

    print("DeepAgent initialized with FilesystemBackend ('agent_data').")
    return agent

if __name__ == "__main__":
    initialize_deep_agent()
