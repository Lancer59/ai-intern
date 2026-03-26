from langchain_mcp_adapters.client import MultiServerMCPClient

# Standardized MCP Server Configurations
# To add a new server, just add a new entry to this dictionary.
MCP_CONFIGS = {
    "microsoft-docs": {
        "url": "https://learn.microsoft.com/api/mcp",
        "transport": "sse"
    }
}
async def get_mcp_tools():
    client = MultiServerMCPClient(
        {
            # "microsoft-docs": {
            #     "command": "python",
            #     # Make sure to update to the full absolute path to your math_server.py file
            #     "args": ["/path/to/math_server.py"],
            #     "transport": "stdio",
            # },
            "microsoft-docs": {
                "url": "https://learn.microsoft.com/api/mcp",
                "transport": "http",
            }
        }
    )
    tools = await client.get_tools()
    return tools