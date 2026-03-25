import asyncio
import os
from coding_assistant import create_coding_assistant

async def main():
    print("=== AI Coding Assistant CLI ===")
    
    # 1. Get Workspace Path relative to parent folder
    # Current project is in /ai-intern, we look for sibling folders in /ALLPROJECTS
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    
    project_folder_name = input(f"Enter the project folder name in '{parent_dir}': ").strip()
    if not project_folder_name:
        workspace = current_dir # Default to current agent dir if empty
    else:
        workspace = os.path.join(parent_dir, project_folder_name)
    
    # Ensure workspace is absolute for the backend
    workspace = os.path.abspath(workspace)
    print(f"Initializing assistant for: {workspace}...")
    
    try:
        agent = create_coding_assistant(workspace)
        print("Assistant ready! Type 'exit' to quit.")

        while True:
            user_query = input("\n[User]: ").strip()
            if user_query.lower() in ["exit", "quit", "bye"]:
                break
            
            if not user_query:
                continue

            print("\n[Assistant]: ", end="", flush=True)
            
            # 2. Stream Response
            input_data = {"messages": [("user", user_query)]}
            
            async for event in agent.astream_events(input_data, version="v2", config={"recursion_limit": 200}):
                kind = event["event"]
                
                # Stream tokens
                if kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if content:
                        print(content, end="", flush=True)
                
                # Show tool activity
                elif kind == "on_tool_start":
                    tool_input = event["data"].get("input")
                    print(f"\n[Tool]: {event['name']} is starting...")
                    if tool_input:
                        print(f"       Input: {tool_input}")
                
                elif kind == "on_tool_end":
                    tool_output = event["data"].get("output")
                    print(f"\n[Tool]: {event['name']} finished.")
                    if tool_output:
                        # Truncate long outputs for readability
                        str_output = str(tool_output)
                        if len(str_output) > 200:
                            str_output = str_output[:200] + "..."
                        print(f"       Output: {str_output}")

            print("\n")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
