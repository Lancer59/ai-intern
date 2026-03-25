import asyncio
from deep_agent_init import initialize_deep_agent

async def run_streaming_agent():
    """
    Invokes the DeepAgent using astream_events and prints tokens/events in real-time.
    """
    try:
        # 1. Initialize the agent
        agent = initialize_deep_agent()

        print("\n--- Starting DeepAgent Stream ---")
        
        # 2. Prepare the input
        input_data = {"messages": [("user", "Hello! Can you help me plan a simple task?")]}

        # 3. Stream events
        # version="v2" is standard for latest LangChain/LangGraph astream_events
        async for event in agent.astream_events(input_data, version="v2"):
            kind = event["event"]
            
            # Case 1: Final Answer Tokens (on_chat_model_stream)
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    print(content, end="", flush=True)

            # Case 2: Tool Calls
            elif kind == "on_tool_start":
                print(f"\n[Tool Start]: {event['name']}")
            
            elif kind == "on_tool_end":
                print(f"\n[Tool End]: {event['name']} -> Result: {event['data']['output']}")

            # Case 3: Metadata/Planning events (specific to deepagents)
            elif kind == "on_chain_start" and event.get("name") == "DeepAgent":
                print(f"\n[DeepAgent Started planning...]")

        print("\n--- Stream Finished ---")

    except Exception as e:
        print(f"\n[Error during streaming]: {e}")

if __name__ == "__main__":
    # Ensure nested loop if running in environment with existing loop (or use asyncio.run)
    try:
        asyncio.run(run_streaming_agent())
    except RuntimeError:
        # For Jupyter or environments where loop is already running
        loop = asyncio.get_event_loop()
        loop.create_task(run_streaming_agent())
