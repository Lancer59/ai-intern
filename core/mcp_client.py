import os
import logging
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
# Standardized MCP Server Configurations
# To add a new server, just add a new entry to this dictionary.
MCP_CONFIGS = {
    "microsoft-docs": {
        "url": "https://learn.microsoft.com/api/mcp",
        "transport": "http"
    },
    "tavily":{
        "url":f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}",
        "transport": "http"
    },
    "deepwiki":{
        "url":"https://mcp.deepwiki.com/mcp",
        "transport": "http"
    }
}
async def get_mcp_tools():
    try:
        client = MultiServerMCPClient(
            MCP_CONFIGS
        )
        tools = await client.get_tools()
        return tools
    except Exception as e:
        logger.warning(f"mcp tools are not loaded: {e}")
        return []